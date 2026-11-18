-- NGLA Map and Tracking Overhaul: the settings page (Options > Scripts > NGLA Map and Tracking Overhaul).
-- Values live in permanent storage, so they apply to every save. map.lua and
-- compass.lua read them through storage.playerSection(...) and react to changes.

local I = require('openmw.interfaces')

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

return {}
