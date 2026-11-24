-- NGLA Map and Tracking Overhaul: the settings page (Options > Scripts > NGLA Map and Tracking Overhaul).
--
-- Registered from a menu script, so the page is there from the main menu as well
-- as in game. Values live in permanent storage and apply to every save; map.lua
-- and compass.lua read them through storage.playerSection(...) and react to changes.

local I = require('openmw.interfaces')
local input = require('openmw.input')
local async = require('openmw.async')

-- ------------------------------------------------------------------ key binding widget

-- Stores a plain key code in NGLA's own setting. The built-in inputBinding renderer
-- is avoided on purpose: it uses a binding registry shared between mods, and other
-- mods have reported rebinding one overwriting another.
local recording = nil      -- { set, value } while waiting for a key

I.Settings.registerRenderer('NGLA/keyBinding', function(value, set)
    local label
    if recording then
        label = 'Press a key... (Esc to cancel)'
    else
        label = value and input.getKeyName(value) or 'None'
    end
    return {
        template = I.MWUI.templates.textNormal,
        props = { text = label },
        events = {
            mouseClick = async:callback(function()
                if recording then return end
                recording = { set = set, value = value }
                set(value)         -- redraw, showing the prompt
            end),
        },
    }
end)

-- ------------------------------------------------------------------ page and groups

I.Settings.registerPage {
    key = 'NGLA',
    l10n = 'NGLA',
    name = 'pageName',
    description = 'pageDescription',
}

I.Settings.registerGroup {
    key = 'SettingsNGLACompass',
    page = 'NGLA',
    l10n = 'NGLA',
    name = 'compassGroup',
    permanentStorage = true,
    order = 0,
    settings = {
        { key = 'enabled', renderer = 'checkbox', default = true,
          name = 'compassEnabled', description = 'compassEnabledDesc' },
        { key = 'scale', renderer = 'number', default = 1.5, argument = { min = 0.5, max = 2.0 },
          name = 'compassScale', description = 'compassScaleDesc' },
        { key = 'posX', renderer = 'number', default = 0.5, argument = { min = 0, max = 1 },
          name = 'compassPosX', description = 'compassPosXDesc' },
        { key = 'posY', renderer = 'number', default = 0.05, argument = { min = 0, max = 1 },
          name = 'compassPosY', description = 'compassPosYDesc' },
        { key = 'showLabel', renderer = 'checkbox', default = true,
          name = 'compassLabel', description = 'compassLabelDesc' },
    },
}

I.Settings.registerGroup {
    key = 'SettingsNGLATracking',
    page = 'NGLA',
    l10n = 'NGLA',
    name = 'trackingGroup',
    permanentStorage = true,
    order = 1,
    settings = {
        { key = 'maxTracked', renderer = 'number', default = 5,
          argument = { integer = true, min = 1, max = 5 },
          name = 'maxTracked', description = 'maxTrackedDesc' },
        { key = 'autoClear', renderer = 'checkbox', default = true,
          name = 'autoClear', description = 'autoClearDesc' },
    },
}

I.Settings.registerGroup {
    key = 'SettingsNGLAFastTravel',
    page = 'NGLA',
    l10n = 'NGLA',
    name = 'travelGroup',
    permanentStorage = true,
    order = 2,
    settings = {
        { key = 'enabled', renderer = 'checkbox', default = true,
          name = 'travelEnabled', description = 'travelEnabledDesc' },
        { key = 'passTime', renderer = 'checkbox', default = false,
          name = 'travelPassTime', description = 'travelPassTimeDesc' },
        { key = 'visitedOnly', renderer = 'checkbox', default = false,
          name = 'travelVisitedOnly', description = 'travelVisitedOnlyDesc' },
    },
}

-- A, B and X aren't offered: they select, close and pin on the map itself.
I.Settings.registerGroup {
    key = 'SettingsNGLAControls',
    page = 'NGLA',
    l10n = 'NGLA',
    name = 'controlsGroup',
    permanentStorage = true,
    order = 3,
    settings = {
        { key = 'mapKey', renderer = 'NGLA/keyBinding', default = input.KEY.M,
          name = 'mapKey', description = 'mapKeyDesc' },
        { key = 'mapButton', renderer = 'select', default = 'padNone',
          argument = { l10n = 'NGLA', items = { 'padNone', 'padY', 'padLeftShoulder', 'padRightShoulder',
              'padLeftStick', 'padRightStick', 'padBack', 'padStart',
              'padDPadUp', 'padDPadDown', 'padDPadLeft', 'padDPadRight' } },
          name = 'mapButton', description = 'mapButtonDesc' },
    },
}

return {
    engineHandlers = {
        onKeyPress = function(key)
            if not recording then return end
            local r = recording
            recording = nil
            if key.code == input.KEY.Escape then
                r.set(r.value)
            else
                r.set(key.code)
            end
        end,
    },
}
