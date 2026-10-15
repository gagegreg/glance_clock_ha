"""Calendar geometry and custom scenes, ported from the Mac prototype.

No network or HA dependencies: these render using Hypfer's documented protocol.
The clock has 48 columns, four rings and a fixed color palette (not RGB).
"""

import math
import unicodedata
from dataclasses import dataclass, replace
from datetime import datetime

from ..glance_pb2 import CustomScene


@dataclass(frozen=True)
class Meeting:
    key: str
    title: str
    start: datetime
    end: datetime
    color: int


@dataclass(frozen=True)
class Segment:
    start: int
    length: int
    lane: int
    height: int
    color: int
    meeting: str = ""

    @property
    def packed(self):
        if not (
            0 <= self.start < 48
            and 1 <= self.length <= 48 - self.start
            and 0 <= self.lane < 4
            and 1 <= self.height <= 4 - self.lane
            and 0 <= self.color <= 53
        ):
            raise ValueError("Invalid ring segment")
        return (
            self.start
            | self.lane << 6
            | (self.length - 1) << 8
            | (self.height - 1) << 14
            | self.color << 16
        )


CLEAR = Segment(0, 48, 0, 4, 0).packed
TEAM_COLORS = {
    "msu_football": (22, 12),
    "msu_basketball": (22, 12),
    "michigan_football": (15, 1),
    "tigers": (15, 2),
    "lions": (16, 12),
}
EFFECTS = (
    "none",
    "glow",
    "wave",
    "breath_1",
    "breath_2",
    "dim_once",
    "dim_twice",
    "fire",
    "wheel",
    "flower",
    "flower2",
    "fan",
    "sun",
    "thunderstorm",
    "cloud",
    "snow",
    "rain",
    "fog",
)


def calendar_segments(meetings, now):
    """Fill isolated events; stack overlaps inward in event-start order.

    Absolute quarter-hours are converted to the clock's local timezone. During
    a DST fall-back, the nearer occurrence owns a repeated wall-clock column.
    More than four concurrent events are counted but cannot be drawn.
    """
    stamp = now.timestamp()
    events = sorted(
        (
            m
            for m in meetings
            if m.end.timestamp() > stamp
            and m.start.timestamp() < stamp + 43200
            and m.end.timestamp() > m.start.timestamp()
        ),
        key=lambda m: (m.start.timestamp(), m.key),
    )
    cells = [[None] * 48 for _ in range(4)]
    hidden, seen = set(), set()
    quarter = int(stamp // 900) * 900
    for offset in range(48):
        start = quarter + offset * 900
        local = datetime.fromtimestamp(start, now.tzinfo)
        column = local.hour % 12 * 4 + local.minute // 15
        if column in seen:
            continue
        seen.add(column)
        active = [
            m
            for m in events
            if m.start.timestamp() < start + 900
            and m.end.timestamp() > max(start, stamp)
        ]
        hidden.update(m.key for m in active[4:])
        if active:
            for lane in range(4):
                cells[lane][column] = active[min(lane, len(active) - 1)]
    segments = []
    for lane, row in enumerate(cells):
        start = 0
        while start < 48:
            meeting = row[start]
            end = start + 1
            while end < 48 and row[end] == meeting:
                end += 1
            if meeting:
                prior = next(
                    (
                        i
                        for i, s in enumerate(segments)
                        if s.start == start
                        and s.length == end - start
                        and s.lane + s.height == lane
                        and s.meeting == meeting.key
                    ),
                    None,
                )
                if prior is not None:
                    segments[prior] = replace(
                        segments[prior], height=segments[prior].height + 1
                    )
                else:
                    segments.append(
                        Segment(start, end - start, lane, 1, meeting.color, meeting.key)
                    )
            start = end
    return segments, len(hidden)


def clock_text(text):
    text = " ".join(text.split())
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore")[:64]


def scene_packet(
    segments,
    *,
    text="",
    duration=12,
    effect="none",
    colors=(15, 12),
    sound=0,
    meeting=None,
):
    """Build one acknowledged-write scene, retaining calendar under the text.

    Pulse is a firmware pixel effect, not calibrated brightness dimming. GIF
    colors are fixed; only glow/wave accept a pair of palette colors.
    """
    if effect not in EFFECTS or not 3 <= duration <= 30 or not 0 <= sound <= 17:
        raise ValueError("Invalid announcement settings")
    scene = CustomScene()

    def obj(method, start=0, life=1):
        return scene.object.add(method=method, startTime=start, lifeTime=life, result=0)

    base = [CLEAR] + [s.packed for s in segments]
    obj(2).fill.segment.extend(base)
    if text:
        obj(4, life=duration * 50).text.add(text=clock_text(text))
    restore_at = 0
    if effect in ("glow", "wave"):
        areas = [
            Segment(0, 48, 0, 1, colors[0]).packed,
            Segment(0, 48, 3, 1, colors[1]).packed,
        ]
        obj(2).fill.segment.extend([CLEAR] + areas)
        animation = obj(7, life=150).areaAnimation
        animation.type = 1 if effect == "wave" else 0
        animation.area.extend(areas)
        if effect == "wave":
            animation.wave.speed = 1
        else:
            animation.pulse.riseTime = animation.pulse.fallTime = 75
        restore_at = 150
    elif effect.startswith(("breath_", "dim_")):
        pixels = [
            Segment(column, 1, lane, 1, s.color).packed
            for s in segments
            if s.meeting == meeting
            for lane in range(s.lane, s.lane + s.height)
            for column in range(s.start, s.start + s.length)
            if (column + lane) % 4 == 0
        ]
        half, cycles = {
            "breath_1": (duration * 25, 1),
            "breath_2": (40, 2),
            "dim_once": (8, 1),
            "dim_twice": (8, 2),
        }[effect]
        if pixels:
            restore_at = half * 2 * cycles
            animation = obj(7, life=restore_at).areaAnimation
            animation.type = 0
            animation.area.extend(pixels)
            animation.pulse.riseTime = animation.pulse.fallTime = half
    elif effect in ("snow", "rain", "fog"):
        weather = obj(9, life=150).weather
        weather.condition = ("snow", "rain", "fog").index(effect)
        weather.position = 0
        weather.intensity = 5
        restore_at = 150
    elif effect != "none":
        gif = obj(8, life=150).gif
        gif.type = (
            "fire",
            "wheel",
            "flower",
            "flower2",
            "fan",
            "sun",
            "thunderstorm",
            "cloud",
        ).index(effect) + 10
        gif.segment = 782080
        gif.speed = 3
        restore_at = 150
    if restore_at:
        obj(2, start=restore_at).fill.segment.extend(base)
    if sound:
        obj(3).sound = sound
    packet = bytes([0, 0, 24 if text else 8, 7]) + scene.SerializeToString()
    if len(packet) > 512:
        raise ValueError(
            "Scene exceeds the BLE 512-byte write limit; select fewer calendars or a simpler effect"
        )
    return packet


def parse_events(response, calendar_colors, timezone):
    """HA calendar.get_events response; omit all-day and cancelled events."""
    meetings = []
    for entity, color in calendar_colors.items():
        for event in response[entity]["events"]:
            if event.get("status") == "cancelled":
                continue
            start, end = event.get("start", ""), event.get("end", "")
            if "T" not in start or "T" not in end:
                continue
            start = datetime.fromisoformat(start)
            end = datetime.fromisoformat(end)
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone)
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone)
            title = event.get("summary", "Meeting")
            key = f"{entity}:{event.get('uid', title)}:{start.isoformat()}:{end.isoformat()}"
            meetings.append(Meeting(key, title, start, end, color))
    return list({m.key: m for m in meetings}.values())


def weather_announcement(state, attributes, unit):
    """Use the selected HA provider's units, optionally converting C/F."""
    if state in ("unknown", "unavailable"):
        raise ValueError("Weather provider is unavailable")
    temperature = float(attributes["temperature"])
    if not math.isfinite(temperature):
        raise ValueError("Weather temperature is invalid")
    source = attributes.get("temperature_unit", "").replace("°", "")
    if source not in ("C", "F"):
        raise ValueError("Weather provider must report Celsius or Fahrenheit")
    target = source if unit == "native" else unit
    if target != source:
        temperature = (
            temperature * 9 / 5 + 32 if target == "F" else (temperature - 32) * 5 / 9
        )
    effect = {
        "sunny": "sun",
        "clear-night": "none",
        "partlycloudy": "cloud",
        "cloudy": "cloud",
        "rainy": "rain",
        "pouring": "rain",
        "fog": "fog",
        "snowy": "snow",
        "snowy-rainy": "snow",
        "lightning": "thunderstorm",
        "lightning-rainy": "thunderstorm",
    }.get(state, "none")
    return f"{temperature:.0f}{target} {state.replace('-', ' ')}", effect
