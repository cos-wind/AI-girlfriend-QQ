from __future__ import annotations

from .support import InsightsStoreMixin


class EvaluationsMixin(InsightsStoreMixin):
    def create_evaluation(
        self,
        *,
        turn_id: str,
        conversation_id: str,
        group_id: str,
        question: str,
        answer: str,
        context: str,
        judge_model: str,
        source: str = "system",
        model_type: str = "chat",
        model_name: str = "",
    ) -> str:
        evaluation_id = uuid.uuid4().hex
        with self._connect() as db:
            db.execute(
                """INSERT INTO evaluations
                (id, turn_id, conversation_id, group_id, question, answer, context, source, model_type, model_name, judge_model, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    evaluation_id,
                    str(turn_id),
                    str(conversation_id),
                    str(group_id or ""),
                    str(question)[:12000],
                    str(answer)[:16000],
                    str(context)[:24000],
                    str(source or "system")[:30],
                    str(model_type or "chat")[:20],
                    str(model_name or "")[:160],
                    str(judge_model),
                    utc_now(),
                ),
            )
        return evaluation_id

    def queued_evaluation_ids(self, limit: int = 500) -> list[str]:
        with self._connect() as db:
            db.execute("UPDATE evaluations SET status='queued', started_at=NULL WHERE status='running'")
            rows = db.execute(
                "SELECT id FROM evaluations WHERE status='queued' ORDER BY created_at LIMIT ?",
                (max(1, min(5000, limit)),),
            ).fetchall()
        return [str(row["id"]) for row in rows]

    def evaluation_input(self, evaluation_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM evaluations WHERE id=?", (evaluation_id,)).fetchone()
        return dict(row) if row else None

    def mark_evaluation_running(self, evaluation_id: str) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE evaluations SET status='running', started_at=?, error='' WHERE id=?",
                (utc_now(), evaluation_id),
            )

    def complete_evaluation(
        self,
        evaluation_id: str,
        *,
        scores: dict[str, dict[str, Any]],
        semantic_similarity: float | None,
        overall_score: float | None,
        issues: list[str],
    ) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM evaluation_scores WHERE evaluation_id=?", (evaluation_id,))
            db.executemany(
                """INSERT INTO evaluation_scores
                (evaluation_id, dimension, score, reason, metadata_json) VALUES (?, ?, ?, ?, ?)""",
                [
                    (
                        evaluation_id,
                        dimension,
                        data.get("score"),
                        str(data.get("reason") or "")[:2000],
                        _json(data.get("metadata") or {}),
                    )
                    for dimension, data in scores.items()
                ],
            )
            db.execute(
                """UPDATE evaluations SET status='completed', semantic_similarity=?, overall_score=?,
                issues_json=?, error='', completed_at=? WHERE id=?""",
                (semantic_similarity, overall_score, _json(issues), utc_now(), evaluation_id),
            )

    def fail_evaluation(self, evaluation_id: str, error: str) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE evaluations SET status='failed', error=?, completed_at=? WHERE id=?",
                (str(error)[:2000], utc_now(), evaluation_id),
            )

    def retry_evaluation(self, evaluation_id: str) -> bool:
        with self._connect() as db:
            cursor = db.execute(
                """UPDATE evaluations SET status='queued', error='', started_at=NULL,
                completed_at=NULL WHERE id=? AND status='failed'""",
                (evaluation_id,),
            )
        return cursor.rowcount > 0

    def failed_evaluation_ids(self, source: str = "", limit: int = 5000) -> list[str]:
        """返回失败任务，供配置修正后的批量重试使用。"""
        clause = " AND source=?" if source in {"system", "model"} else ""
        params: list[Any] = [source] if source in {"system", "model"} else []
        params.append(max(1, min(20000, int(limit))))
        with self._connect() as db:
            rows = db.execute(
                f"SELECT id FROM evaluations WHERE status='failed'{clause} ORDER BY created_at LIMIT ?",
                params,
            ).fetchall()
        return [str(row["id"]) for row in rows]

    def list_evaluations(
        self,
        *,
        status: str = "",
        source: str = "",
        model_type: str = "",
        dimension: str = "",
        maximum_score: float | None = None,
        query: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        where: list[str] = []
        params: list[Any] = []
        if status:
            where.append("e.status=?")
            params.append(status)
        if source in {"system", "model"}:
            where.append("e.source=?")
            params.append(source)
        if model_type in {"chat", "vision", "voice"}:
            where.append("e.model_type=?")
            params.append(model_type)
        if query:
            where.append("(e.question LIKE ? OR e.answer LIKE ? OR e.conversation_id LIKE ?)")
            pattern = f"%{query[:100]}%"
            params.extend([pattern, pattern, pattern])
        if maximum_score is not None:
            where.append("e.overall_score<=?")
            params.append(float(maximum_score))
        if dimension:
            where.append("EXISTS (SELECT 1 FROM evaluation_scores f WHERE f.evaluation_id=e.id AND f.dimension=?)")
            params.append(dimension)
        clause = " WHERE " + " AND ".join(where) if where else ""
        safe_limit = max(1, min(500, int(limit)))
        safe_offset = max(0, int(offset))
        with self._connect() as db:
            total = int(db.execute(f"SELECT COUNT(*) FROM evaluations e{clause}", params).fetchone()[0])
            rows = db.execute(
                f"""SELECT e.*, GROUP_CONCAT(s.dimension || ':' || COALESCE(ROUND(s.score,2),'null'), '|') AS score_pairs
                FROM evaluations e LEFT JOIN evaluation_scores s ON s.evaluation_id=e.id
                {clause} GROUP BY e.id ORDER BY e.created_at DESC LIMIT ? OFFSET ?""",
                [*params, safe_limit, safe_offset],
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            pairs = str(item.pop("score_pairs") or "")
            item["scores"] = {
                key: (None if value == "null" else float(value))
                for key, value in (part.split(":", 1) for part in pairs.split("|") if ":" in part)
            }
            item["issues"] = _loads(item.pop("issues_json", "[]"), [])
            item["question"] = str(item["question"])[:500]
            item["answer"] = str(item["answer"])[:700]
            item.pop("context", None)
            items.append(item)
        return {"items": items, "total": total, "limit": safe_limit, "offset": safe_offset}

    def evaluation_detail(self, evaluation_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM evaluations WHERE id=?", (evaluation_id,)).fetchone()
            scores = db.execute(
                "SELECT dimension, score, reason, metadata_json FROM evaluation_scores WHERE evaluation_id=?",
                (evaluation_id,),
            ).fetchall()
        if not row:
            return None
        result = dict(row)
        result["issues"] = _loads(result.pop("issues_json", "[]"), [])
        result["scores"] = {
            str(score["dimension"]): {
                "score": score["score"],
                "reason": score["reason"],
                "metadata": _loads(score["metadata_json"], {}),
            }
            for score in scores
        }
        return result

    def evaluation_dashboard(self, days: int = 30, source: str = "", model_type: str = "") -> dict[str, Any]:
        safe_days = max(1, min(3650, int(days)))
        modifier = f"-{safe_days} days"
        source_clause = " AND source=?" if source in {"system", "model"} else ""
        model_clause = " AND model_type=?" if model_type in {"chat", "vision", "voice"} else ""
        source_param: tuple[Any, ...] = (source,) if source in {"system", "model"} else ()
        model_param: tuple[Any, ...] = (model_type,) if model_type in {"chat", "vision", "voice"} else ()
        filter_params = (modifier, *source_param, *model_param)
        with self._connect() as db:
            counts = db.execute(
                f"""SELECT COUNT(*) AS total,
                SUM(status='completed') AS completed, SUM(status='failed') AS failed,
                SUM(status IN ('queued','running')) AS pending,
                AVG(CASE WHEN status='completed' THEN overall_score END) AS average
                FROM evaluations WHERE datetime(created_at)>=datetime('now', ?){source_clause}{model_clause}""",
                filter_params,
            ).fetchone()
            dimensions = db.execute(
                f"""SELECT s.dimension, AVG(s.score) AS average, COUNT(s.score) AS samples
                FROM evaluation_scores s JOIN evaluations e ON e.id=s.evaluation_id
                WHERE datetime(e.created_at)>=datetime('now', ?){source_clause}{model_clause}
                GROUP BY s.dimension ORDER BY s.dimension""",
                filter_params,
            ).fetchall()
            trend_rows = db.execute(
                f"""SELECT substr(created_at,1,10) AS day, overall_score FROM evaluations
                WHERE status='completed' AND overall_score IS NOT NULL
                AND datetime(created_at)>=datetime('now', ?){source_clause}{model_clause}
                ORDER BY day, created_at""",
                filter_params,
            ).fetchall()
            issues_rows = db.execute(
                f"""SELECT issues_json FROM evaluations WHERE status='completed'
                AND datetime(created_at)>=datetime('now', ?){source_clause}{model_clause} AND issues_json!='[]'""",
                filter_params,
            ).fetchall()
            model_rows = db.execute(
                f"""SELECT model_type, COUNT(*) AS total,
                    SUM(status='completed') AS completed,
                    SUM(status='failed') AS failed,
                    SUM(status IN ('queued','running')) AS pending,
                    AVG(CASE WHEN status='completed' THEN overall_score END) AS average
                FROM evaluations WHERE datetime(created_at)>=datetime('now', ?){source_clause}
                GROUP BY model_type ORDER BY model_type""",
                (modifier, *source_param),
            ).fetchall()
        issue_counts: dict[str, int] = {}
        for row in issues_rows:
            for issue in _loads(row["issues_json"], []):
                key = str(issue)[:120]
                issue_counts[key] = issue_counts.get(key, 0) + 1
        grouped_scores: dict[str, list[float]] = {}
        for row in trend_rows:
            try:
                grouped_scores.setdefault(str(row["day"]), []).append(float(row["overall_score"]))
            except (TypeError, ValueError):
                continue
        trend: list[dict[str, Any]] = []
        previous_average: float | None = None
        for day, values in grouped_scores.items():
            bucket = _trend_bucket(day, values, previous_average)
            trend.append(bucket)
            previous_average = float(bucket["average"])
        all_scores = [value for values in grouped_scores.values() for value in values]
        trend_meta = _trend_bucket("window", all_scores, None) if all_scores else {
            "average": None, "median": None, "p25": None, "p75": None,
            "minimum": None, "maximum": None, "samples": 0, "quality_index": None,
            "volatility": None, "low_score_rate": None, "delta": None,
        }
        return {
            "counts": dict(counts or {}),
            "dimensions": [dict(row) for row in dimensions],
            "trend": trend,
            "trend_meta": trend_meta,
            "top_issues": [
                {"issue": issue, "count": count}
                for issue, count in sorted(issue_counts.items(), key=lambda item: (-item[1], item[0]))[:10]
            ],
            "model_types": [dict(row) for row in model_rows],
            "delivery": self.delivery_dashboard(safe_days, model_type),
        }
