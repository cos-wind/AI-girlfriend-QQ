from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any


GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
DEFAULT_WEATHER_TIMEOUT_SECONDS = 8.0

WEATHER_CODE_LABELS = {
    0: "晴",
    1: "大致晴朗",
    2: "局部多云",
    3: "阴",
    45: "有雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "毛毛雨",
    55: "较强毛毛雨",
    56: "轻微冻毛毛雨",
    57: "较强冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "轻微冻雨",
    67: "较强冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "米雪",
    80: "小阵雨",
    81: "中等阵雨",
    82: "强阵雨",
    85: "小阵雪",
    86: "强阵雪",
    95: "雷暴",
    96: "雷暴伴小冰雹",
    99: "雷暴伴强冰雹",
}

CHINA_PROVINCE_PREFIXES = (
    "内蒙古自治区",
    "广西壮族自治区",
    "西藏自治区",
    "宁夏回族自治区",
    "新疆维吾尔自治区",
    "黑龙江省",
    "北京市",
    "天津市",
    "上海市",
    "重庆市",
    "河北省",
    "山西省",
    "辽宁省",
    "吉林省",
    "江苏省",
    "浙江省",
    "安徽省",
    "福建省",
    "江西省",
    "山东省",
    "河南省",
    "湖北省",
    "湖南省",
    "广东省",
    "海南省",
    "四川省",
    "贵州省",
    "云南省",
    "陕西省",
    "甘肃省",
    "青海省",
    "台湾省",
    "香港特别行政区",
    "澳门特别行政区",
    "内蒙古",
    "黑龙江",
    "广西",
    "西藏",
    "宁夏",
    "新疆",
    "北京",
    "天津",
    "上海",
    "重庆",
    "河北",
    "山西",
    "辽宁",
    "吉林",
    "江苏",
    "浙江",
    "安徽",
    "福建",
    "江西",
    "山东",
    "河南",
    "湖北",
    "湖南",
    "广东",
    "海南",
    "四川",
    "贵州",
    "云南",
    "陕西",
    "甘肃",
    "青海",
    "台湾",
    "香港",
    "澳门",
)


async def get_weather(
    arguments: dict[str, Any] | None = None,
    config: Any | None = None,
) -> str:
    args = arguments or {}
    location = str(args.get("location") or "").strip()
    if not location:
        return "天气查询失败：缺少城市或地区名称。不要猜测用户所在地。"

    timeout = max(
        2.0,
        float(
            getattr(config, "web_search_timeout_seconds", DEFAULT_WEATHER_TIMEOUT_SECONDS)
            or DEFAULT_WEATHER_TIMEOUT_SECONDS
        ),
    )
    try:
        import httpx

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            places = None
            for candidate in _location_candidates(location):
                geocoding_response = await client.get(
                    GEOCODING_URL,
                    params={
                        "name": candidate,
                        "count": 3,
                        "language": "zh",
                        "format": "json",
                    },
                )
                geocoding_response.raise_for_status()
                geocoding = geocoding_response.json()
                places = geocoding.get("results") if isinstance(geocoding, dict) else None
                if isinstance(places, list) and places:
                    break
            if not isinstance(places, list) or not places:
                return f"天气查询失败：没有找到“{location}”对应的地点，请补充城市或地区。"

            place = places[0]
            forecast_response = await client.get(
                FORECAST_URL,
                params={
                    "latitude": place["latitude"],
                    "longitude": place["longitude"],
                    "current": (
                        "temperature_2m,relative_humidity_2m,apparent_temperature,"
                        "precipitation,rain,weather_code,cloud_cover,wind_speed_10m"
                    ),
                    "daily": (
                        "weather_code,temperature_2m_max,temperature_2m_min,"
                        "precipitation_probability_max"
                    ),
                    "timezone": "auto",
                    "forecast_days": 3,
                },
            )
            forecast_response.raise_for_status()
            forecast = forecast_response.json()
        return format_weather_result(location, place, forecast)
    except Exception as exc:
        return (
            f"天气查询失败：{_short_error(exc)}。"
            "不要编造实时天气，可以直接说明当前天气数据源不可用。"
        )


def format_weather_result(
    requested_location: str,
    place: dict[str, Any],
    forecast: dict[str, Any],
) -> str:
    current = forecast.get("current") if isinstance(forecast, dict) else None
    daily = forecast.get("daily") if isinstance(forecast, dict) else None
    if not isinstance(current, dict) or not current:
        return f"天气查询失败：没有拿到“{requested_location}”的当前天气数据。"

    place_name = _place_label(place)
    observed_at = str(current.get("time") or "时间未知")
    timezone_name = str(forecast.get("timezone") or place.get("timezone") or "当地时区")
    weather_label = weather_code_label(current.get("weather_code"))
    temperature = _value(current, "temperature_2m", "°C")
    apparent = _value(current, "apparent_temperature", "°C")
    humidity = _value(current, "relative_humidity_2m", "%")
    precipitation = _value(current, "precipitation", " mm")
    cloud_cover = _value(current, "cloud_cover", "%")
    wind_speed = _value(current, "wind_speed_10m", " km/h")
    queried_at = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        f"天气数据查询时间：{queried_at} Asia/Shanghai",
        f"匹配地点：{place_name}（用户输入：{requested_location}）",
        f"数据时刻：{observed_at} {timezone_name}",
        (
            f"当前：{weather_label}，{temperature}，体感 {apparent}，"
            f"湿度 {humidity}，降水 {precipitation}，云量 {cloud_cover}，风速 {wind_speed}。"
        ),
    ]
    forecast_lines = _daily_forecast_lines(daily)
    if forecast_lines:
        lines.append("未来三天：")
        lines.extend(forecast_lines)
    lines.append(
        "数据源：Open-Meteo 天气预报模型。回答时应说明这是模型天气数据，不要称为本地气象站实测值。"
    )
    return "\n".join(lines)


def weather_code_label(value: Any) -> str:
    try:
        code = int(value)
    except (TypeError, ValueError):
        return "天气状况未知"
    return WEATHER_CODE_LABELS.get(code, f"天气代码 {code}")


def _daily_forecast_lines(daily: Any) -> list[str]:
    if not isinstance(daily, dict):
        return []
    dates = daily.get("time")
    codes = daily.get("weather_code")
    maximums = daily.get("temperature_2m_max")
    minimums = daily.get("temperature_2m_min")
    rain_chances = daily.get("precipitation_probability_max")
    if not isinstance(dates, list):
        return []

    lines: list[str] = []
    for index, date in enumerate(dates[:3]):
        lines.append(
            f"- {date}：{weather_code_label(_at(codes, index))}，"
            f"{_display(_at(minimums, index))}–{_display(_at(maximums, index))}°C，"
            f"最高降水概率 {_display(_at(rain_chances, index))}%。"
        )
    return lines


def _place_label(place: dict[str, Any]) -> str:
    parts = [
        str(place.get("country") or "").strip(),
        str(place.get("admin1") or "").strip(),
        str(place.get("admin2") or "").strip(),
        str(place.get("name") or "").strip(),
    ]
    unique: list[str] = []
    for part in parts:
        if part and part not in unique:
            unique.append(part)
    return " ".join(unique) or "未知地点"


def _location_candidates(location: str) -> list[str]:
    normalized = re.sub(r"\s+", "", location).removeprefix("中国")
    candidates = [location.strip(), normalized]
    for prefix in CHINA_PROVINCE_PREFIXES:
        if normalized.startswith(prefix) and len(normalized) > len(prefix):
            remainder = normalized[len(prefix) :].lstrip("省市")
            candidates.extend([remainder, remainder.rstrip("市区县")])
            break

    unique: list[str] = []
    for candidate in candidates:
        cleaned = candidate.strip()
        if len(cleaned) >= 2 and cleaned not in unique:
            unique.append(cleaned)
    return unique


def _value(data: dict[str, Any], key: str, unit: str) -> str:
    return f"{_display(data.get(key))}{unit}"


def _display(value: Any) -> str:
    if value is None:
        return "未知"
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def _at(values: Any, index: int) -> Any:
    if not isinstance(values, list) or index >= len(values):
        return None
    return values[index]


def _short_error(exc: Exception) -> str:
    text = " ".join((str(exc).strip() or exc.__class__.__name__).split())
    return text[:160]
