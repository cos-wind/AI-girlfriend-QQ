"""Bounded, declarative figures. Neither extraction nor rendering executes user code."""
from __future__ import annotations

import math
import re


def _text(value, limit=120, *, required=False):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError(f'图表文字应为{1 if required else 0}至{limit}字')
    return value.strip()


def _list(value, limit, minimum=0):
    if not isinstance(value, list) or not minimum <= len(value) <= limit:
        raise ValueError(f'图表列表应有{minimum}至{limit}项')
    return value


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e12:
        raise ValueError('图表数值必须有限且绝对值不大于1e12，缺失值请用 null')
    return value


def _object(value):
    if not isinstance(value, dict):
        raise ValueError('图表对象格式错误')
    return value


def validate_charts(value, *, evidence=None):
    """When machine-generated, require a verbatim source and observed numeric values.

    Numeric presence is a guard against invented measurements, not a statistical
    or semantic verification of labels, units or causal claims.
    """
    charts = []
    budget = 0
    for item in _list(value, 4):
        item = _object(item)
        kind = item.get('type')
        if kind not in ('bar', 'line', 'scatter', 'flow', 'matrix'):
            raise ValueError('支持柱状、折线、散点、流程和矩阵图')
        source = _text(item.get('source', ''), 2400, required=True)
        if evidence is not None and source not in evidence:
            raise ValueError('自动图表需要可核对的连续原文来源')
        chart = dict(type=kind, title=_text(item.get('title', ''), 100, required=True),
                     source=source, notes=_text(item.get('notes', ''), 1000), metrics=[])
        for metric in _list(item.get('metrics', []), 4):
            metric = _object(metric)
            chart['metrics'].append({key: _text(metric.get(key, ''), limit, required=key != 'note')
                                     for key, limit in [('label', 50), ('value', 50), ('note', 100)]})
        numbers = [float(n) for m in chart['metrics'] for n in re.findall(r'[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?', m['value'].replace('−', '-'))]
        if kind in ('bar', 'line', 'scatter'):
            chart.update(x_label=_text(item.get('x_label', ''), 80), y_label=_text(item.get('y_label', ''), 80), series=[])
            if kind == 'bar':
                chart['labels'] = [_text(v, 80, required=True) for v in _list(item.get('labels'), 24, 1)]
            for series in _list(item.get('series'), 8, 1):
                series = _object(series)
                style = series.get('style', 'solid')
                if style not in ('solid', 'dash', 'dot'):
                    raise ValueError('未知线型')
                values = []
                for point in _list(series.get('values'), 2000, 1):
                    if kind == 'bar':
                        values.append(None if point is None else _number(point))
                        if point is not None:
                            numbers.append(point)
                    else:
                        _list(point, 2, 2)
                        x = _number(point[0])
                        y = None if point[1] is None else _number(point[1])
                        values.append([x, y])
                        numbers.extend([x] + ([y] if y is not None else []))
                if kind == 'bar' and len(values) != len(chart['labels']):
                    raise ValueError('每组柱状数据必须与分类数量相同')
                budget += len(values)
                if kind == 'line' and any(a[0] >= b[0] for a, b in zip(values, values[1:])):
                    raise ValueError('折线横坐标必须严格递增')
                if not any(v is not None if kind == 'bar' else v[1] is not None for v in values):
                    raise ValueError('每组至少需要一个有效数值')
                chart['series'].append(dict(name=_text(series.get('name', ''), 80, required=True), style=style, values=values))
            trend = item.get('trend', False)
            if type(trend) is not bool:
                raise ValueError('trend 必须为布尔值')
            chart['trend'] = trend if kind == 'scatter' else False
        elif kind == 'matrix':
            chart['columns'] = [_text(v, 60, required=True) for v in _list(item.get('columns'), 5, 1)]
            chart['rows'] = []
            for row in _list(item.get('rows'), 16, 1):
                row = _object(row)
                cells = []
                for cell in _list(row.get('cells'), len(chart['columns']), len(chart['columns'])):
                    cell = _object(cell)
                    status = cell.get('status', 'neutral')
                    if status not in ('good', 'bad', 'neutral', 'info'):
                        raise ValueError('未知矩阵状态')
                    cells.append(dict(text=_text(cell.get('text', ''), 240, required=True), status=status))
                chart['rows'].append(dict(label=_text(row.get('label', ''), 60, required=True), cells=cells))
        else:
            chart['nodes'], chart['edges'] = [], []
            occupied, ids = set(), set()
            for node in _list(item.get('nodes'), 24, 1):
                node = _object(node)
                ident = _text(node.get('id', ''), 40, required=True)
                col, row = node.get('col', 0), node.get('row', 0)
                if type(col) is not int or type(row) is not int or not 0 <= col < 4 or not 0 <= row < 12 or (col, row) in occupied or ident in ids:
                    raise ValueError('流程节点位置应唯一：col 为0至3，row 为0至11，id不可重复')
                occupied.add((col, row)); ids.add(ident)
                status = node.get('status', 'info')
                if status not in ('good', 'bad', 'neutral', 'info'):
                    raise ValueError('未知流程节点状态')
                chart['nodes'].append(dict(id=ident, col=col, row=row, status=status, text=_text(node.get('text', ''), 300, required=True)))
            for edge in _list(item.get('edges', []), 40):
                edge = _object(edge)
                start = _text(edge.get('from', ''), 40, required=True)
                end = _text(edge.get('to', ''), 40, required=True)
                if start not in ids or end not in ids or start == end:
                    raise ValueError('流程连线必须引用不同的已有节点')
                chart['edges'].append({'from': start, 'to': end, 'label': _text(edge.get('label', ''), 40)})
        if evidence is not None:
            numeric_source = re.sub(r'(?<=\d),(?=\d{3}(?:\D|$))', '', source.replace('−', '-'))
            observed = {float(n) for n in re.findall(r'[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?', numeric_source)}
            if any(float(n) not in observed for n in numbers):
                raise ValueError('图表包含来源未出现的数值，请提供实际测量数据，不能推测采样点')
        charts.append(chart)
    if budget > (240 if evidence is not None else 6000):
        raise ValueError('图表数据过多，请按区间拆分或导入降采样后的数据')
    return charts
