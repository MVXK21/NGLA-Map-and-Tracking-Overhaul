-- OpenMW Map Markers: Skyrim-style compass with tracked destinations.
--
-- Compass strip method and textures from "Horizontal Compass" by Valcule,
-- used and modified with credit as its permissions allow.
--
-- Additions: markers for the destinations tracked on the map
-- (I.MapMarkers.getTracked), camera yaw instead of player yaw, NorthMarker
-- data generated per load order, and inside interiors the marker points at
-- the way out towards the destination.

local ui = require('openmw.ui')
local util = require('openmw.util')
local self = require('openmw.self')
local camera = require('openmw.camera')
local I = require('openmw.interfaces')

local interiors = require('scripts.MapMarkers.generated.interiors')

local v2 = util.vector2
local rgb = util.color.rgb
local TAU = 2 * math.pi

-- ------------------------------------------------------------------ geometry
local SCALE = 1.0
local COMPASS_W, COMPASS_H = math.floor(420 * SCALE), math.floor(28 * SCALE)
local STRIP_W = math.floor(2048 * SCALE)          -- the strip texture covers 360 degrees, N at x = 0
local FRAME_W, FRAME_H = math.floor(520 * SCALE), math.floor(68 * SCALE)
local POSITION = v2(0.5, 0.05)                    -- same spot as Horizontal Compass's default
local ANCHOR = v2(0.5, 0.4)
local MARKER_W, MARKER_H = math.floor(14 * SCALE), math.floor(21 * SCALE)

local TEX = 'textures/MapMarkers/compass/'
local LETTER_COLOR = rgb(1, 1, 1)
local FRAME_COLOR = rgb(1, 0.8, 0.4)
local LABEL_COLOR = rgb(0.95, 0.88, 0.7)
local UNITS_TO_M = 0.01428                        -- Morrowind: roughly 70 units per metre

-- Sign applied to NorthMarker rotation when turning the strip inside interiors.
-- Only affects the N/E/S/W letters indoors; the markers don't use it.
local NORTH_SIGN = 1

-- ------------------------------------------------------------------ UI

local function tex(name) return ui.texture { path = TEX .. name } end

local stripTile = tex('compass.png')
local pinTex = ui.texture { path = 'textures/MapMarkers/icons/pin.png' }
local strip = ui.create {
    type = ui.TYPE.Widget,
    props = { size = v2(STRIP_W * 3, COMPASS_H) },
    content = ui.content {
        { type = ui.TYPE.Image, props = { resource = stripTile, color = LETTER_COLOR,
            size = v2(STRIP_W + 2, COMPASS_H), position = v2(0, 0) } },
        { type = ui.TYPE.Image, props = { resource = stripTile, color = LETTER_COLOR,
            size = v2(STRIP_W + 2, COMPASS_H), position = v2(STRIP_W - 1, 0) } },
        { type = ui.TYPE.Image, props = { resource = stripTile, color = LETTER_COLOR,
            size = v2(STRIP_W + 2, COMPASS_H), position = v2(STRIP_W * 2 - 2, 0) } },
    },
}

local markers = ui.create {
    type = ui.TYPE.Widget,
    props = { size = v2(COMPASS_W, COMPASS_H) },
    content = ui.content {},
}

local label = ui.create {
    type = ui.TYPE.Text,
    props = {
        text = '', textSize = math.floor(16 * SCALE), textColor = LABEL_COLOR, textShadow = true,
        relativePosition = v2(0.5, 1), anchor = v2(0.5, 0), position = v2(0, 2),
    },
}

local root = ui.create {
    layer = 'HUD',
    type = ui.TYPE.Widget,
    props = { relativePosition = POSITION, anchor = ANCHOR, size = v2(FRAME_W, FRAME_H), visible = false },
    content = ui.content {
        { type = ui.TYPE.Image, props = { resource = tex('compass_background.png'), size = v2(FRAME_W, FRAME_H) } },
        {
            -- clipped viewport: children outside its bounds aren't drawn
            type = ui.TYPE.Widget,
            props = {
                size = v2(COMPASS_W, COMPASS_H),
                position = v2(math.floor((FRAME_W - COMPASS_W) / 2), math.floor((FRAME_H - COMPASS_H) / 2)),
            },
            content = ui.content { strip, markers },
        },
        { type = ui.TYPE.Image, props = { resource = tex('compass_overlay.png'), color = FRAME_COLOR,
            size = v2(FRAME_W, FRAME_H) } },
        label,
    },
}

-- ------------------------------------------------------------------ helpers

local function wrap(a)   -- -> (-pi, pi]
    a = a % TAU
    if a > math.pi then a = a - TAU end
    return a
end

local function cellKey(cell)
    return (cell.name or ''):lower()
end

-- Where to point for a destination at world (tx, ty), from the current cell.
-- Returns x, y in the current cell's coordinates, and whether that's an exit door.
local function aimPoint(cell, tx, ty)
    if cell.isExterior then return tx, ty, false end
    if cell:hasTag('QuasiExterior') then return nil end
    local key = cellKey(cell)
    local outs = interiors.exits[key]
    if outs then
        local best, bestD
        for _, o in ipairs(outs) do
            local dx, dy = o[3] - tx, o[4] - ty
            local d = dx * dx + dy * dy
            if not bestD or d < bestD then best, bestD = o, d end
        end
        return best[1], best[2], true
    end
    local r = interiors.route[key]
    if r then return r[1], r[2], true end
    return nil
end

local lastVisible = false

local function setVisible(v)
    if v ~= lastVisible then
        lastVisible = v
        root.layout.props.visible = v
        root:update()
    end
end

-- ------------------------------------------------------------------ per frame

local function onFrame()
    local show = I.UI.isHudVisible() and I.UI.getMode() == nil
    setVisible(show)
    if not show then return end

    local cell = self.cell
    if not cell then return end
    local yaw = camera.getYaw()

    -- strip
    local stripYaw = yaw
    if not cell.isExterior then
        stripYaw = yaw - NORTH_SIGN * (interiors.north[cellKey(cell)] or 0)
    end
    local t = (stripYaw / TAU) % 1
    strip.layout.props.position = v2(math.floor(-(t * STRIP_W) - STRIP_W + COMPASS_W / 2), 0)
    strip:update()

    -- markers
    local content = {}
    local labelText, labelRel = '', nil
    local tracked = I.MapMarkers and I.MapMarkers.getTracked() or {}
    local pos = self.position
    for _, dest in ipairs(tracked) do
        local t = dest
        local ax, ay, viaExit = aimPoint(cell, t.x, t.y)
        if ax then
            local dx, dy = ax - pos.x, ay - pos.y
            local rel = wrap(math.atan2(dx, dy) - yaw)
            local x = COMPASS_W / 2 + rel / TAU * STRIP_W
            local alpha = 1
            local half = MARKER_W / 2
            if x < half then x, alpha = half, 0.45
            elseif x > COMPASS_W - half then x, alpha = COMPASS_W - half, 0.45 end
            content[#content + 1] = {
                type = ui.TYPE.Image,
                props = {
                    resource = pinTex,
                    color = t.color, alpha = alpha,
                    size = v2(MARKER_W, MARKER_H),
                    position = v2(math.floor(x - half), math.floor((COMPASS_H - MARKER_H) / 2)),
                },
            }
            -- label: the destination nearest the middle of the compass
            if not labelRel or math.abs(rel) < labelRel then
                labelRel = math.abs(rel)
                if viaExit then
                    labelText = t.name .. '  (exit this way)'
                else
                    local d = math.sqrt(dx * dx + dy * dy) * UNITS_TO_M
                    labelText = string.format('%s  %d m', t.name, math.floor(d + 0.5))
                end
            end
        end
    end
    markers.layout.content = ui.content(content)
    markers:update()

    if label.layout.props.text ~= labelText then
        label.layout.props.text = labelText
        label:update()
    end
end

return {
    engineHandlers = { onFrame = onFrame },
}
