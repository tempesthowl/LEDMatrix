# Soccer Scoreboard Plugin Update Plan

## Overview

Update the soccer scoreboard plugin to achieve parity with the football scoreboard plugin and add custom league management similar to how custom RSS feeds work in the news plugin.

## Reference Repositories

- **Current Soccer Plugin**: `/home/chuck/Github/ledmatrix-soccer-scoreboard/`
- **Football Plugin (Reference)**: `/var/home/chuck/Github/ledmatrix-football-scoreboard/`
- **News Plugin (Custom Feeds Reference)**: `/home/chuck/Github/ledmatrix-news/`
- **v2.5 Soccer Manager (Legacy Reference)**: `https://github.com/ChuckBuilds/LEDMatrix/tree/v2.5/src/soccer_managers.py`
- **Web UI Widgets**: `/var/home/chuck/Github/LEDMatrix/web_interface/static/v3/js/widgets/`

---

## Part 1: Bring Soccer Plugin to Parity with Football Plugin

### 1.1 Manager Architecture Updates

The football plugin uses a **league registry system** for extensibility. Soccer should adopt the same pattern.

**Current Soccer Structure:**
- Hardcoded league keys: `LEAGUE_KEYS = ['eng.1', 'esp.1', 'ger.1', ...]`
- Managers created per league with manual attribute names (`eng1_live`, `esp1_live`, etc.)
- No centralized registry

**Target Structure (from Football):**
```python
# League registry: maps league IDs to their configuration and managers
self._league_registry: Dict[str, Dict[str, Any]] = {}

# Registry format:
{
    'league_id': {
        'enabled': bool,
        'priority': int,           # Display priority (lower = higher priority)
        'live_priority': bool,     # Whether live priority is enabled
        'managers': {
            'live': Manager,
            'recent': Manager,
            'upcoming': Manager
        }
    }
}
```

**Changes Required:**
- [ ] Add `_initialize_league_registry()` method
- [ ] Add `_get_enabled_leagues_for_mode(mode_type)` method
- [ ] Add `_is_league_complete_for_mode(league_id, mode_type)` method
- [ ] Add `_get_league_manager_for_mode(league_id, mode_type)` method
- [ ] Refactor `_get_current_manager()` to use registry
- [ ] Refactor display logic to use sequential block display architecture

### 1.2 Sequential Block Display Architecture

Football plugin documents this clearly:
> Sequential block display shows all games from one league before moving to the next.

**Changes Required:**
- [ ] Implement `_get_managers_in_priority_order(mode_type)`
- [ ] Implement `_try_manager_display()` with proper progress tracking
- [ ] Add game transition logging (throttled)
- [ ] Track `_current_game_tracking` for transition detection

### 1.3 Dynamic Duration Improvements

Football has granular per-league/per-mode dynamic duration settings.

**Football Schema Structure:**
```json
{
  "nfl": {
    "dynamic_duration": {
      "enabled": false,
      "min_duration_seconds": 30,
      "max_duration_seconds": null,
      "modes": {
        "live": { "enabled": false, "min_duration_seconds": null, "max_duration_seconds": null },
        "recent": { ... },
        "upcoming": { ... }
      }
    }
  }
}
```

**Changes Required:**
- [ ] Update `config_schema.json` to add per-league `dynamic_duration` with nested `modes`
- [ ] Add `min_duration_seconds` support (soccer only has max currently)
- [ ] Update `supports_dynamic_duration()` to check granular settings
- [ ] Update `get_dynamic_duration_cap()` to check granular settings
- [ ] Add `_get_dynamic_duration_min()` method

### 1.4 Per-Game Duration Settings

Football has `live_game_duration`, `recent_game_duration`, `upcoming_game_duration` per league.

**Changes Required:**
- [ ] Add these settings to each league in `config_schema.json`
- [ ] Pass these to managers via `_adapt_config_for_manager()`
- [ ] Ensure managers respect these durations

### 1.5 Filtering Options

Football has a structured `filtering` object per league.

**Current Soccer:** Has `show_favorite_teams_only` and `show_all_live` at league level
**Target:** Move to nested `filtering` object for consistency

```json
{
  "filtering": {
    "show_favorite_teams_only": true,
    "show_all_live": false
  }
}
```

**Changes Required:**
- [ ] Update `config_schema.json` to use `filtering` object pattern
- [ ] Update `_adapt_config_for_manager()` to handle new structure

### 1.6 Display Mode Settings

Both plugins already have `live_display_mode`, `recent_display_mode`, `upcoming_display_mode` with `switch`/`scroll` options. Soccer appears to be at parity here.

### 1.7 Customization Options (Font Settings)

Football has a `customization` section for font settings per text element type.

**Changes Required:**
- [ ] Add `customization` section to soccer `config_schema.json`
- [ ] Support: `score_text`, `period_text`, `team_name`, `status_text`, `detail_text`, `rank_text`
- [ ] Each with `font` and `font_size` properties
- [ ] Update managers to use customization config

### 1.8 Missing Tracking Features

Football has several tracking features soccer lacks:

**Changes Required:**
- [ ] Add `_single_game_manager_start_times` tracking
- [ ] Add `_game_id_start_times` tracking (prevents resets when game order changes)
- [ ] Add `_display_mode_to_managers` tracking
- [ ] Add `_last_display_mode` and `_last_display_mode_time` tracking
- [ ] Add `_mode_start_time` for per-mode duration enforcement
- [ ] Add throttled logging for `has_live_content()` when returning False

---

## Part 2: Custom League Management (Similar to News Custom Feeds)

### 2.1 Feature Overview

Users should be able to:
1. Add custom soccer leagues by providing ESPN league code
2. Enable/disable individual custom leagues
3. Delete custom leagues
4. Custom leagues appear alongside predefined leagues in the UI

### 2.2 Schema Changes

Add `custom_leagues` array similar to news plugin's `custom_feeds`:

```json
{
  "custom_leagues": {
    "type": "array",
    "description": "Custom soccer leagues. Add leagues by their ESPN league code.",
    "minItems": 0,
    "maxItems": 20,
    "x-widget": "custom-leagues",
    "items": {
      "type": "object",
      "properties": {
        "name": {
          "type": "string",
          "minLength": 1,
          "maxLength": 100,
          "description": "Display name for the league (e.g., 'Liga Portugal')"
        },
        "league_code": {
          "type": "string",
          "minLength": 1,
          "maxLength": 50,
          "description": "ESPN league code (e.g., 'por.1', 'mex.1', 'arg.1')"
        },
        "priority": {
          "type": "integer",
          "default": 50,
          "minimum": 1,
          "maximum": 100,
          "description": "Display priority (1=highest, 100=lowest). Lower numbers display first."
        },
        "enabled": {
          "type": "boolean",
          "default": true,
          "description": "Whether this league is enabled"
        },
        "favorite_teams": {
          "type": "array",
          "items": { "type": "string" },
          "default": [],
          "description": "Favorite team abbreviations for this league"
        },
        "live_priority": {
          "type": "boolean",
          "default": false,
          "description": "Give live games from this league priority"
        },
        "display_modes": {
          "type": "object",
          "properties": {
            "live": { "type": "boolean", "default": true },
            "recent": { "type": "boolean", "default": true },
            "upcoming": { "type": "boolean", "default": true },
            "live_display_mode": { "type": "string", "enum": ["switch", "scroll"], "default": "switch" },
            "recent_display_mode": { "type": "string", "enum": ["switch", "scroll"], "default": "switch" },
            "upcoming_display_mode": { "type": "string", "enum": ["switch", "scroll"], "default": "switch" }
          }
        },
        "game_limits": {
          "type": "object",
          "properties": {
            "recent_games_to_show": { "type": "integer", "default": 5, "minimum": 1, "maximum": 20 },
            "upcoming_games_to_show": { "type": "integer", "default": 10, "minimum": 1, "maximum": 20 }
          }
        },
        "live_game_duration": {
          "type": "integer",
          "default": 20,
          "minimum": 10,
          "maximum": 120,
          "description": "Duration in seconds to display each live game"
        },
        "recent_game_duration": {
          "type": "integer",
          "default": 15,
          "minimum": 5,
          "maximum": 60,
          "description": "Duration in seconds to display each recent game"
        },
        "upcoming_game_duration": {
          "type": "integer",
          "default": 15,
          "minimum": 5,
          "maximum": 60,
          "description": "Duration in seconds to display each upcoming game"
        },
        "filtering": {
          "type": "object",
          "properties": {
            "show_favorite_teams_only": { "type": "boolean", "default": false },
            "show_all_live": { "type": "boolean", "default": true }
          }
        },
        "dynamic_duration": {
          "type": "object",
          "properties": {
            "enabled": { "type": "boolean", "default": false },
            "min_duration_seconds": { "type": "number", "minimum": 10, "maximum": 300 },
            "max_duration_seconds": { "type": "number", "minimum": 60, "maximum": 600 },
            "modes": {
              "type": "object",
              "properties": {
                "live": {
                  "type": "object",
                  "properties": {
                    "enabled": { "type": "boolean" },
                    "min_duration_seconds": { "type": "number" },
                    "max_duration_seconds": { "type": "number" }
                  }
                },
                "recent": { "type": "object" },
                "upcoming": { "type": "object" }
              }
            }
          }
        }
      },
      "required": ["name", "league_code"]
    }
  }
}
```

### 2.3 Plugin Code Changes

**Changes Required:**
- [ ] Add `_load_custom_leagues()` method to parse `custom_leagues` config
- [ ] Create managers dynamically for custom leagues using a factory pattern
- [ ] Add custom leagues to the league registry with appropriate priority
- [ ] Support custom league ESPN API endpoints
- [ ] Handle logo loading for custom leagues (may need to download from ESPN)

### 2.4 Web UI Widget

Create a new `custom-leagues.js` widget based on `custom-feeds.js`:

**File:** `/var/home/chuck/Github/LEDMatrix/web_interface/static/v3/js/widgets/custom-leagues.js`

**Features:**
- Table-based editor with columns: Name, League Code, Priority, Enabled, Actions
- Add/Remove league rows
- Enable/disable toggle per league
- Priority input (1-100, default 50)
- No logo upload (logos fetched from ESPN)
- **API validation on blur**: When user enters a league code and leaves the field, validate via ESPN API
- Validation endpoint: `GET https://site.api.espn.com/apis/site/v2/sports/soccer/{league_code}/scoreboard`
- Show green checkmark if valid, red X with error message if invalid
- Suggest common league codes in placeholder/tooltip

### 2.5 API Endpoint for League Validation

Add a new API endpoint to proxy ESPN validation (to avoid CORS issues):

**Endpoint:** `GET /api/v3/plugins/soccer-scoreboard/validate-league?code={league_code}`

**Response:**
```json
{
  "status": "success",
  "valid": true,
  "league_name": "Liga Portugal",
  "league_code": "por.1"
}
```
or
```json
{
  "status": "error",
  "valid": false,
  "message": "League code not found"
}
```

### 2.6 Manager Factory for Custom Leagues

Create a generic soccer manager factory that can create managers for any ESPN league code:

```python
def create_custom_league_managers(
    league_code: str,
    league_name: str,
    config: Dict[str, Any],
    display_manager,
    cache_manager
) -> Tuple[SoccerLiveManager, SoccerRecentManager, SoccerUpcomingManager]:
    """Create managers for a custom league."""
    # Configure ESPN API endpoint
    api_endpoint = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league_code}/scoreboard"

    # Create managers with custom endpoint
    live = SoccerLiveManager(config, display_manager, cache_manager, api_endpoint=api_endpoint)
    recent = SoccerRecentManager(config, display_manager, cache_manager, api_endpoint=api_endpoint)
    upcoming = SoccerUpcomingManager(config, display_manager, cache_manager, api_endpoint=api_endpoint)

    return live, recent, upcoming
```

---

## Part 3: Visual Parity with v2.5 Soccer Manager

### 3.1 Scorebug Layout

From v2.5 `soccer_managers.py` analysis:
- Logo positions: left/right edges
- Team abbreviations at bottom
- Scores centered
- Status display: "HT", "FT", minute markers ("45'"), stoppage time

**Changes Required:**
- [ ] Verify current scorebug layout matches v2.5
- [ ] Ensure time display formats match: "HT", "FT", "45'", "45'+2"
- [ ] Verify logo positioning

### 3.2 Game State Display

v2.5 supported:
- Upcoming: "Next Game" header, date, kickoff time centered
- Live: Live clock with minute marker
- Final: "FT" status with final score

**Changes Required:**
- [ ] Verify all game states display correctly
- [ ] Ensure "Next Game" header for upcoming matches

---

## Implementation Order

### Phase 1: Config Schema Updates (Foundation)
1. Update predefined league schemas with:
   - Per-league game durations (`live_game_duration`, `recent_game_duration`, `upcoming_game_duration`)
   - Nested `filtering` object
   - Enhanced `dynamic_duration` with `min_duration_seconds` and per-mode settings
   - `customization` section for fonts
2. Add `custom_leagues` array schema with full feature parity

### Phase 2: Architecture Updates (Parity with Football)
1. Add league registry system (`_league_registry`, `_initialize_league_registry()`)
2. Add registry helper methods:
   - `_get_enabled_leagues_for_mode(mode_type)`
   - `_is_league_complete_for_mode(league_id, mode_type)`
   - `_get_league_manager_for_mode(league_id, mode_type)`
3. Implement sequential block display architecture
4. Add missing tracking features:
   - `_single_game_manager_start_times`
   - `_game_id_start_times`
   - `_display_mode_to_managers`
   - `_current_game_tracking`
   - `_mode_start_time`
5. Update dynamic duration methods for granular settings

### Phase 3: Custom Leagues Backend
1. Add manager factory for custom leagues
2. Implement `_load_custom_leagues()` method
3. Add custom leagues to registry with user-defined priority
4. Handle ESPN API endpoints for custom league codes

### Phase 4: Web UI for Custom Leagues
1. Create `custom-leagues.js` widget
2. Add league validation API endpoint
3. Test widget add/remove/enable functionality

### Phase 5: Testing & Polish
1. Test with multiple predefined leagues enabled
2. Test custom league addition/removal/validation
3. Test priority ordering (predefined vs custom)
4. Verify scroll mode works with mixed leagues
5. Verify dynamic duration calculations
6. Visual comparison with v2.5 soccer manager

---

## Files to Modify

### Soccer Plugin (`/home/chuck/Github/ledmatrix-soccer-scoreboard/`)
- `manager.py` - Major refactor for registry system, tracking, custom leagues
- `config_schema.json` - Add all new schema features
- `soccer_managers.py` - Add factory pattern support, custom league endpoints

### Web Interface (`/var/home/chuck/Github/LEDMatrix/web_interface/`)
- Create `static/v3/js/widgets/custom-leagues.js` - New widget for custom league management
- Update `blueprints/api_v3.py` - Add league validation endpoint
- May need to update template partials for custom widget rendering

### Potentially
- `manifest.json` - If display modes change

---

## Estimated Scope

- **Part 1 (Parity)**: Medium-large - Significant refactoring of manager.py
- **Part 2 (Custom Leagues)**: Medium - New feature, new widget
- **Part 3 (Visual)**: Small - Verification and minor fixes

---

## Design Decisions (Confirmed)

1. **Custom leagues feature parity**: ✅ Full parity
   - Custom leagues get all the same settings as predefined leagues (dynamic duration, scroll mode, per-game durations, filtering, etc.)

2. **ESPN league code validation**: ✅ Yes, validate via API
   - Make an ESPN API call to verify the league code exists before saving
   - Show user-friendly error if league code is invalid

3. **Custom league priority**: ✅ User-configurable
   - Let users set priority order for each custom league
   - Add `priority` field to custom league schema (integer, 1-100)
   - Lower number = higher priority (displays first)

4. **Common ESPN league codes to suggest in UI**:
   - `por.1` (Liga Portugal)
   - `mex.1` (Liga MX)
   - `arg.1` (Argentina Primera División)
   - `bra.1` (Brasileirão)
   - `ned.1` (Eredivisie)
   - `sco.1` (Scottish Premiership)
   - `tur.1` (Turkish Süper Lig)
   - `bel.1` (Belgian Pro League)
