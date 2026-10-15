# Clock apps — development branch

This is the first HA port of the Mac clock apps. It reuses PorlyBe's BLE
connection and Hypfer's scene protocol. It is ready for hardware testing,
not a claim of tested HA-to-clock behavior. The Mac remains the working host
until we explicitly hand the clock over. Only one host should control it.

## What is implemented

| App | First HA version |
| --- | --- |
| Calendar | Next 12 hours from selected `calendar.*` entities; full wedges and stacked overlaps; per-calendar palette colors; rotating meeting titles; Breath 1/2 and brief pixel pulses |
| Weather | Choose any `weather.*` entity/provider/location configured in HA; native, F or C; current temperature/condition with firmware animation |
| Sports | Announcement action with default MSU, Michigan, Tigers and Lions colors, plus color overrides; an HA automation supplies score text |
| Other announcements | Text, sound, animation and two-color glow/wave; useful for calendar alerts |

The calendar is the base display. Announcements share an eight-item queue,
expire after 60 seconds, and restore the current calendar afterward. Sound
defaults to off. Refreshes cannot interrupt an app announcement. On reconnect
only the calendar is restored; old sounds/announcements are not replayed.

The legacy `send_notice`, timer and forecast actions still work independently;
they do not participate in the app queue. Avoid mixing them with a persistent
calendar app because the firmware scene priorities can supersede the app scene.

## Install for testing

1. Back up HA. Add `gagegreg/glance_clock_ha` as a custom integration repository
   in HACS, select the `1.3.0b1` beta release, then restart HA. This beta contains
   the generic clock apps; BYB remains on its separate branch. Alternatively,
   copy this branch's `custom_components/glance_clock` directory into HA's
   `config/custom_components/glance_clock`, then restart HA.
2. Configure the integration/BLE connection using upstream's instructions.
   Do not factory-reset or flash a working clock just to install these apps.
   Hand time still needs a working Bluetooth Current Time Service; this code
   does not implement or validate that service or ESPHome proxy compatibility.
3. Configure Google Calendar using HA's Google Calendar integration. Other
   calendar providers work too. No Mac OAuth credentials need to be copied.
4. Configure a weather provider for Ann Arbor (or your preferred location).
   Provider/location selection lives in HA; choose its weather entity here.
5. In **Developer tools → Actions**, try the examples below. The optional
   `entry_id` selects the clock configuration entry, not its MAC or entity ID.
   It is required for multiple clocks. Find it in Developer tools → Template
   with `{{ config_entry_id('light.YOUR_CLOCK_LIGHT') }}` using your clock's
   actual light entity ID.

Google Calendar setup: https://www.home-assistant.io/integrations/google/
Calendar event API: https://www.home-assistant.io/integrations/calendar/
Weather providers: https://www.home-assistant.io/integrations/weather/

## Calendar

```yaml
action: glance_clock.show_calendar
data:
  calendars:
    calendar.greg: blue
    calendar.sanja: lime_green
    calendar.lila: blue_violet
    calendar.jane: dark_orange
```

Replace these example entity IDs with your own. Use calendar entities, not
their `state` attributes: those expose only one event. `calendar.get_events`
returns overlapping events. All-day/cancelled/ended events are omitted.
The clock has 48 quarter-hour columns and four bands. The earliest event is
outermost during overlap; each isolated event fills all four bands. A fifth
concurrent event cannot be shown (a warning reports the hidden count).

Refresh every five minutes with `blueprints/automation/glance_clock/calendar.yaml`.
Copy the blueprint to HA's `config/blueprints/automation/glance_clock/`, then
create an automation from it. It also fetches after HA starts. The cached
calendar is redrawn every minute to remove ended events. If fetching fails
for over 15 minutes, wedges clear instead of showing stale data. The cache
is intentionally not persisted; the automation repopulates it after restart.
Send `calendars: {}` and disable the refresh automation to clear the base.

```yaml
action: glance_clock.announce_calendar
data:
  effect: breath_1  # One slow breath over the scroll; breath_2 gives two brief breaths. Also: dim_once, dim_twice, none
  duration: 20
```

Each call rotates to the next visible meeting. Text and the cue start together.
These use the firmware's **pixel pulse**, not a smooth brightness dimmer.
Long names are transliterated/truncated to 64 ASCII bytes; increase duration
up to 30 seconds to allow long text to scroll.

Meeting alerts can use HA calendar triggers with offsets, including separate
triggers for -00:05:00, -00:01:00 and 00:00:00. Add/remove offsets to choose
alerts. Use queued automation mode for overlapping meetings:

```yaml
alias: Glance meeting reminders
triggers:
  - trigger: calendar
    entity_id: calendar.greg
    event: start
    offset: '-00:05:00'
  - trigger: calendar
    entity_id: calendar.greg
    event: start
    offset: '00:00:00'
actions:
  - action: glance_clock.announce
    data:
      text: '{{ trigger.calendar_event.summary }}'
      sound: rise
      effect: glow
      primary_color: 15
      secondary_color: 12
mode: queued
```

This first alert bridge uses a ring glow; the Mac's meeting-specific alert flash
and dedicated alert-settings UI are not yet ported. HA calendars generally
poll every 15 minutes: create test events sufficiently far ahead.

## Weather and scheduling

```yaml
action: glance_clock.announce_weather
data:
  weather_entity: weather.home
  unit: F
  duration: 12
```

`unit` may be `F`, `C` or `native`. The provider must supply a current
temperature/unit and a state updated within the last hour. Forecast rings
remain available through upstream's separate `send_forecast` action.

Use `scheduled_app.yaml` to choose an interval or comma-separated local times
such as `08:00, 12:30, 18:00`. Add the action above in the blueprint's action
picker. Create another instance for calendar announcements (e.g. every five
minutes). Interval schedules align to midnight rather than elapsed time since
the previous announcement. HA's local time governs schedules; a repeated DST
hour can repeat a time-of-day announcement.

## Sports colors

```yaml
action: glance_clock.announce_sports
data:
  team: msu_football
  text: 'MSU 14 Michigan 7'
  effect: glow
  # Optional overrides, otherwise team colors:
  # primary_color: 22
  # secondary_color: 12
```

| Team key | Default palette |
| --- | --- |
| `msu_football`, `msu_basketball` | green / white |
| `michigan_football` | blue / gold |
| `tigers` | blue / orange |
| `lions` | light blue / white |

Use `glow`, `wave` or `none`. The other firmware animations have fixed colors
and cannot be recolored. Palette IDs useful for overrides: gold 1, orange 2,
red 5, purple 11, white 12, royal blue 14, blue 15, light blue 16, turquoise
18, light green 21, dark green 22, lime 23. These approximate team colors on
the clock's fixed palette.

Automatic ESPN polling/score-change detection from the Mac is **not ported
yet**. A sports sensor/automation can call this action. Its trigger must ignore
initial/unavailable states and unchanged scores to avoid false celebrations.

## Development and next steps

Generic work lives on `feature/clock-apps`. The separate `feature/byb-orders`
branch builds on it and contains the BYB-specific order ledger/actions. No
customer-facing API changes are part of this branch.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-test.txt
.venv/bin/python -m pytest -q
```

Tests exercise protocol decoding, geometry/time boundaries, palette selection,
queues, expiry, disconnect and unload. Full BLE/firmware and HA installation
validation remain required. Scenes exceeding the 512-byte acknowledged-write
limit are rejected rather than split into undocumented commands.

Next: verify a small scene on HA hardware, test CTS/reconnection, add UI options
for app selection, then port sports polling and any richer calendar controls.
