-- NGLA Map and Tracking Overhaul: world map window.
--
-- Replaces the built-in Map window.
--   M            open the map on its own (full size); M again closes it (key and pad button are settings)
--   Tab menu     compact map in the built-in map's usual spot
--   drag         pan                 mouse wheel   zoom
--   left-click   a location: popup with Fast Travel and Mark (just Mark if fast travel is off)
--   right-click  drop a pin on empty map / remove a pin
--   search box   type a name, click a result (or press Enter) to jump to it
--   controller   A select, X pin, B close the popup, right stick zoom

local ui = require('openmw.ui')
local util = require('openmw.util')
local self = require('openmw.self')
local async = require('openmw.async')
local input = require('openmw.input')
local storage = require('openmw.storage')
local core = require('openmw.core')
local nearby = require('openmw.nearby')
local types = require('openmw.types')
local I = require('openmw.interfaces')

local trackingSettings = storage.playerSection('SettingsNGLATracking')
local travelSettings = storage.playerSection('SettingsNGLAFastTravel')
local controlSettings = storage.playerSection('SettingsNGLAControls')

local data = require('scripts.NGLA.generated.data')

local v2 = util.vector2
local rgb = util.color.rgb
local CELL = 8192

local ICONS = 'textures/NGLA/icons/'
local HEADER_H = 28
local SEARCH_W = 240
local ROW_H = 22
local MAX_RESULTS = 8
local ZOOM_MIN, ZOOM_MAX, ZOOM_STEP = 0.06, 8.0, 1.25
local TOWN_ZOOM = 0.7          -- town houses/shops appear at this zoom and closer
local MAX_MARKERS = 900
local DRAG_THRESHOLD = 4       -- pixels the mouse must move before a press becomes a drag
local MAX_TRACKED = 5          -- hard cap (one colour each); the setting picks 1..5

local function mapKey()
    return controlSettings:get('mapKey') or input.KEY.M
end

-- the chosen controller button, or nil ('padLeftShoulder' -> CONTROLLER_BUTTON.LeftShoulder)
local function mapButton()
    local name = controlSettings:get('mapButton')
    if not name or name == 'padNone' then return nil end
    return input.CONTROLLER_BUTTON[name:sub(4)]
end

local function maxTracked()
    local n = math.floor(tonumber(trackingSettings:get('maxTracked')) or MAX_TRACKED)
    return math.max(1, math.min(MAX_TRACKED, n))
end
local PIN_REACHED = 600        -- game units: a pin clears when the player gets this close
local POPUP_ROW_H = 26
local SURVEY_FRAMES = 5        -- frames to wait for nearby actors to answer the combat/follower check
local UNITS_PER_HOUR = 18000   -- optional time cost: roughly walking pace at the default timescale
local MIN_TRAVEL_HOURS, MAX_TRAVEL_HOURS = 0.25, 72
local STICK_DEADZONE = 0.22
local STICK_ZOOM_RATE = 1.6       -- zoom speed at full stick
local STICK_ZOOM_INTERVAL = 0.05  -- seconds between map redraws while zooming

local LAYOUTS = {
    -- M: centred, large
    full = { relativePosition = v2(0.5, 0.5), anchor = v2(0.5, 0.5), w = 0.62, h = 0.72 },
    -- Tab menu: the built-in map window's default place (settings.cfg "map x/y/w/h")
    compact = { relativePosition = v2(0.63, 0.015), anchor = v2(0, 0), w = 0.36, h = 0.37 },
}

local COLOR_ENTRANCE = rgb(0.86, 0.22, 0.18)
local COLOR_LANDMARK = rgb(1.0, 0.85, 0.2)
local COLOR_TOWN = rgb(0.55, 0.6, 1.0)
local COLOR_TEXT = rgb(0.87, 0.78, 0.6)
local COLOR_TEXT_DIM = rgb(0.6, 0.55, 0.45)
local COLOR_HIGHLIGHT = rgb(1, 1, 1)
local TRACK_COLORS = {
    rgb(1.0, 0.75, 0.1), rgb(0.2, 0.9, 1.0), rgb(1.0, 0.35, 0.85), rgb(0.45, 1.0, 0.35), rgb(1.0, 0.5, 0.2),
}

-- ------------------------------------------------------------------ state

local zoom = 0.35                  -- screen pixels per map pixel
local center = nil                 -- map-pixel coordinates at the viewport's centre
local lastExterior = nil           -- {x, y, yaw}: where the player last stood outdoors
local tracked = {}                 -- list of {key, name, x, y, pin, color, kind}
local pinCounter = 0

local visible = false
local mode = nil                   -- 'full' | 'compact'
local openSolo = false             -- set by the M key just before opening
local press = nil                  -- {pos, center, moved}
local mouseOff = nil               -- last cursor offset over the map viewport (nil when off it)
local highlight = nil              -- search result being shown: {mx, my}
local hoverText = nil
local searchText = ''
local results = {}
local visited = {}                 -- lowercase names of cells (and their towns) the player has been in
local pendingTravel = nil          -- {loc, wait, hostile, followers}: running after the map closes
local popupLoc = nil               -- location the click popup is open for
local hiddenGates = {}             -- quest gates whose doors don't exist yet (or any more)
local popupButtons, popupHover = nil, nil  -- the open popup's buttons, and the one under the cursor
local popupAnchor = nil            -- where the popup was opened
local frameCount = 0
local lastMousePressFrame = -10    -- so one press of A can't count as both a click and a pad press
local pendingPadClick = nil        -- frame A was pressed, waiting to see if the engine also clicked
local popupHiddenFrame = -10       -- frame the map closed with the popup open
local keepMap, restoreCenter = nil, nil    -- B closes the popup, not the map behind it
local stickZoomTimer, lastWheelFrame = 0, -100

local pendingClose, typedM = false, false
local clearCheckTimer = 0

local root, mapLayer, resultsEl, popupEl
local header, placeholder
local viewSize
local shownMarkers = {}            -- markers drawn in the last build, for hit testing
local textures = {}

local function tex(path)
    local t = textures[path]
    if not t then
        t = ui.texture { path = path }
        textures[path] = t
    end
    return t
end

-- ------------------------------------------------------------------ coordinates

local function worldToMap(x, y)
    return (x / CELL - data.minCellX) * data.pxPerCell,
           (data.maxCellY + 1 - y / CELL) * data.pxPerCell
end

local function mapToWorld(mx, my)
    return (mx / data.pxPerCell + data.minCellX) * CELL,
           (data.maxCellY + 1 - my / data.pxPerCell) * CELL
end

-- viewport-relative pixel offset -> map pixels
local function viewToMap(off)
    return center.x + (off.x - viewSize.x / 2) / zoom,
           center.y + (off.y - viewSize.y / 2) / zoom
end

local function clampCenter()
    center = v2(math.max(0, math.min(data.mapWidth, center.x)),
                math.max(0, math.min(data.mapHeight, center.y)))
end

local function layerOffset()
    return v2(math.floor(viewSize.x / 2 - center.x * zoom), math.floor(viewSize.y / 2 - center.y * zoom))
end

-- ------------------------------------------------------------------ player

local function playerSpot()
    local cell = self.cell
    if cell and cell.isExterior then
        return self.position.x, self.position.y, self.rotation:getYaw()
    end
    if lastExterior then
        return lastExterior.x, lastExterior.y, lastExterior.yaw
    end
    return nil
end

local function arrowIndex(yaw)
    local step = 2 * math.pi / 16
    return math.floor((yaw % (2 * math.pi)) / step + 0.5) % 16
end

-- ------------------------------------------------------------------ tracking

-- false for a door the current quest state has disabled (Raven Rock before it's built)
local function locExists(loc)
    return not (loc.g and hiddenGates[loc.g])
end

local function locKey(loc)
    return string.format('%s@%d,%d', loc.n, loc.x, loc.y)
end

local function findTracked(key)
    for i, t in ipairs(tracked) do
        if t.key == key then return i, t end
    end
    return nil
end

local function freeColor()
    for i = 1, #TRACK_COLORS do
        local used = false
        for _, t in ipairs(tracked) do
            if t.color == i then used = true break end
        end
        if not used then return i end
    end
    return 1
end

local function untrack(i, message)
    local t = table.remove(tracked, i)
    if t and message then ui.showMessage(message .. t.name) end
end

local function trackLocation(loc)
    local key = locKey(loc)
    local i = findTracked(key)
    if i then
        untrack(i, 'Stopped tracking: ')
        return
    end
    if #tracked >= maxTracked() then
        ui.showMessage(string.format('You can track up to %d destinations. Click one to stop tracking it.', maxTracked()))
        return
    end
    tracked[#tracked + 1] = { key = key, name = loc.n, x = loc.x, y = loc.y, color = freeColor(), kind = loc.k }
    ui.showMessage('Tracking: ' .. loc.n)
end

local function addPin(x, y)
    if #tracked >= maxTracked() then
        ui.showMessage(string.format('You can track up to %d destinations. Right-click a pin to remove it.', maxTracked()))
        return
    end
    pinCounter = pinCounter + 1
    tracked[#tracked + 1] = {
        key = 'pin:' .. pinCounter, name = 'Marked spot ' .. pinCounter,
        x = math.floor(x), y = math.floor(y), pin = true, color = freeColor(),
    }
    ui.showMessage('Pin placed. Right-click it to remove.')
end

-- auto-clear: entering a tracked location's entrance cell, standing in a tracked
-- landmark's exterior cell, or getting close to a pin
local function checkReached()
    if #tracked == 0 or trackingSettings:get('autoClear') == false then return end
    local cell = self.cell
    if not cell then return end
    local cellName = (cell.name or ''):lower()
    for i = #tracked, 1, -1 do
        local t = tracked[i]
        if t.pin then
            if cell.isExterior then
                local dx, dy = self.position.x - t.x, self.position.y - t.y
                if dx * dx + dy * dy < PIN_REACHED * PIN_REACHED then untrack(i, 'Reached ') end
            end
        elseif cellName ~= '' then
            -- "Mournhold" is reached in "Mournhold, Plaza Brindisi Dorom" too
            local n = t.name:lower()
            if cellName == n or cellName:sub(1, #n + 2) == n .. ', ' then untrack(i, 'Reached ') end
        end
    end
end

-- ------------------------------------------------------------------ fast travel

local function recordVisit()
    local name = (self.cell and self.cell.name or ''):lower()
    if name == '' or visited[name] then return end
    visited[name] = true
    local town = name:match('^([^,]+),')       -- "balmora, guild of mages" also counts as Balmora
    if town then visited[town] = true end
end

local function travelEnabled()
    return travelSettings:get('enabled') ~= false
end

-- why this location can't be travelled to right now (nil = it can). The combat
-- check needs an unpaused frame, so it runs after the map closes.
local function travelBlocked(loc)
    if not loc.a then return 'There is no safe place to arrive at ' .. loc.n .. '.' end
    if not types.Player.isTeleportingEnabled(self.object) then return 'You cannot fast travel right now.' end
    if types.Actor.getEncumbrance(self.object) > types.Actor.getCapacity(self.object) then
        return 'You are carrying too much to fast travel.'
    end
    if travelSettings:get('visitedOnly') == true and not visited[loc.n:lower()] then
        return 'You can only fast travel to places you have been to.'
    end
    return nil
end

local function travelHours(loc)
    if travelSettings:get('passTime') ~= true then return 0 end
    local px, py = playerSpot()
    if not px then return MIN_TRAVEL_HOURS end
    local dx, dy = loc.x - px, loc.y - py
    return math.max(MIN_TRAVEL_HOURS, math.min(MAX_TRAVEL_HOURS, math.sqrt(dx * dx + dy * dy) / UNITS_PER_HOUR))
end

local function startTravel(loc)
    pendingTravel = { loc = loc, followers = {}, hostile = false }
    I.UI.setMode()                             -- close the map; the rest runs once the game unpauses
end

local function finishTravel(t)
    pendingTravel = nil
    if t.hostile then
        ui.showMessage('You cannot fast travel while enemies are attacking you.')
        return
    end
    local a = t.loc.a
    core.sendGlobalEvent('NGLA_FastTravel', {
        player = self.object, followers = t.followers, cell = t.loc.ac,
        x = a[1], y = a[2], z = a[3], rot = a[4], ground = t.loc.ag or false,
        hours = travelHours(t.loc),
    })
end

local function onUpdate()
    local t = pendingTravel
    if not t or I.UI.getMode() ~= nil then return end
    if not t.wait then
        for _, actor in ipairs(nearby.actors) do
            if actor ~= self.object then actor:sendEvent('NGLA_Survey', self.object) end
        end
        t.wait = SURVEY_FRAMES
        return
    end
    t.wait = t.wait - 1
    if t.wait <= 0 then finishTravel(t) end
end

local function onSurveyReply(reply)
    local t = pendingTravel
    if not t then return end
    if reply.hostile then t.hostile = true end
    if reply.follower then t.followers[#t.followers + 1] = reply.actor end
end

-- ------------------------------------------------------------------ search

local function trim(s) return (s:gsub('^%s+', ''):gsub('%s+$', '')) end

local function runSearch(text)
    results = {}
    local q = trim(text):lower()
    if #q < 2 then return end
    local found, seen = {}, {}
    for _, loc in ipairs(data.locations) do
        if not loc.s and locExists(loc) then
            local name = loc.n:lower()
            local p = name:find(q, 1, true)
            if p then
                local score
                if p == 1 then score = 0
                elseif name:sub(p - 1, p - 1):match('[%s,%-]') then score = 1
                else score = 2 end
                if loc.t then score = score + 3 end      -- towns' houses after real places
                local key = loc.n
                if not seen[key] or score < seen[key].score then
                    local entry = { loc = loc, score = score }
                    if seen[key] then
                        for j, f in ipairs(found) do if f == seen[key] then found[j] = entry end end
                    else
                        found[#found + 1] = entry
                    end
                    seen[key] = entry
                end
            end
        end
    end
    table.sort(found, function(a, b)
        if a.score ~= b.score then return a.score < b.score end
        return a.loc.n < b.loc.n
    end)
    for i = 1, math.min(MAX_RESULTS, #found) do results[i] = found[i].loc end
end

-- ------------------------------------------------------------------ drawing

-- header and placeholder are their own elements, so updating them never
-- re-renders (and resets) the search box
local function setHeader(text)
    if header and header.layout.props.text ~= text then
        header.layout.props.text = text
        header:update()
    end
end

local function defaultHeader()
    local cell = self.cell
    if cell and not cell.isExterior then
        local name = (cell.displayName and cell.displayName ~= '') and cell.displayName or cell.name
        return 'Inside: ' .. (name or '?')
    end
    return 'World Map'
end

local function image(path, color, size, pos)
    return {
        type = ui.TYPE.Image,
        props = { resource = tex(ICONS .. path), color = color, size = v2(size.x, size.y), position = pos },
    }
end

-- Tile pyramid level for the current zoom: the coarsest level that still has
-- at least one texel per screen pixel (the finest when zoomed in past it).
local function pickLevel()
    local need = zoom * data.pxPerCell        -- screen pixels per cell
    local best = data.levels[1]               -- levels are listed finest first
    for _, lv in ipairs(data.levels) do
        if lv.px >= need then best = lv end
    end
    return best
end

local builtCenter = nil                       -- center at the last buildLayer, for drag refreshes

local function buildLayer()
    local content = {}
    shownMarkers = {}
    builtCenter = center

    -- the visible area plus a margin; tiles and markers outside it aren't drawn
    local half = v2(viewSize.x / zoom * 0.75, viewSize.y / zoom * 0.75)
    local x0, x1 = center.x - half.x, center.x + half.x
    local y0, y1 = center.y - half.y, center.y + half.y

    local lv = pickLevel()
    local span = data.tileSize * data.pxPerCell / lv.px   -- map pixels covered by one tile
    local ts = span * zoom
    for _, t in ipairs(lv.tiles) do
        local tx, ty = t[1] * span, t[2] * span
        if tx + span >= x0 and tx <= x1 and ty + span >= y0 and ty <= y1 then
            content[#content + 1] = {
                type = ui.TYPE.Image,
                props = {
                    resource = tex(string.format('textures/NGLA/map/t%d_%d_%d.png', lv.px, t[1], t[2])),
                    position = v2(math.floor(t[1] * ts), math.floor(t[2] * ts)),
                    size = v2(math.ceil(ts) + 1, math.ceil(ts) + 1),
                },
            }
        end
    end

    local trackedByKey = {}
    for _, t in ipairs(tracked) do trackedByKey[t.key] = t end

    -- ordinary markers inside the visible area (plus a margin), capped
    local count = 0
    for _, loc in ipairs(data.locations) do
        if not loc.s and locExists(loc) and (not loc.t or zoom >= TOWN_ZOOM) then
            local mx, my = worldToMap(loc.x, loc.y)
            if mx >= x0 and mx <= x1 and my >= y0 and my <= y1 then
                local size, color
                if loc.t then size, color = 7, COLOR_TOWN
                elseif loc.k == 'l' then size, color = 11, COLOR_LANDMARK
                else size, color = 10, COLOR_ENTRANCE end
                content[#content + 1] = image('dot.png', color, v2(size, size),
                    v2(math.floor(mx * zoom - size / 2), math.floor(my * zoom - size / 2)))
                shownMarkers[#shownMarkers + 1] = { loc = loc, mx = mx, my = my, r = size / 2 + 3,
                                                    track = trackedByKey[locKey(loc)] }
                count = count + 1
                if count >= MAX_MARKERS then break end
            end
        end
    end

    -- search result highlight
    if highlight then
        local s = 30
        content[#content + 1] = image('ring.png', COLOR_HIGHLIGHT, v2(s, s),
            v2(math.floor(highlight.mx * zoom - s / 2), math.floor(highlight.my * zoom - s / 2)))
    end

    -- tracked destinations: always drawn, whatever the zoom
    for _, t in ipairs(tracked) do
        local mx, my = worldToMap(t.x, t.y)
        local color = TRACK_COLORS[t.color] or TRACK_COLORS[1]
        if t.pin then
            local w, h = 20, 30
            content[#content + 1] = image('pin.png', color, v2(w, h),
                v2(math.floor(mx * zoom - w / 2), math.floor(my * zoom - h)))
            shownMarkers[#shownMarkers + 1] = { pin = t, mx = mx, my = my - h / 2 / zoom, r = 14 }
        else
            local s = 24
            content[#content + 1] = image('ring.png', color, v2(s, s),
                v2(math.floor(mx * zoom - s / 2), math.floor(my * zoom - s / 2)))
        end
    end

    local px, py, yaw = playerSpot()
    if px then
        local mx, my = worldToMap(px, py)
        local s = 28
        content[#content + 1] = image(string.format('arrow_%02d.png', arrowIndex(yaw)), nil, v2(s, s),
            v2(math.floor(mx * zoom - s / 2), math.floor(my * zoom - s / 2)))
    end

    mapLayer.layout.content = ui.content(content)
    mapLayer.layout.props.position = layerOffset()
    mapLayer:update()
end

local function moveLayer()
    -- dragged far enough that the margin runs out: redraw around the new spot
    if builtCenter and math.max(math.abs(center.x - builtCenter.x) * zoom,
                                math.abs(center.y - builtCenter.y) * zoom) > math.min(viewSize.x, viewSize.y) * 0.2 then
        buildLayer()
        return
    end
    mapLayer.layout.props.position = layerOffset()
    mapLayer:update()
end

-- nearest marker under a viewport-relative point (pins win over plain markers)
local function hitTest(off)
    local mx, my = viewToMap(off)
    local best, bestD
    for _, m in ipairs(shownMarkers) do
        local dx, dy = (m.mx - mx) * zoom, (m.my - my) * zoom
        local d = dx * dx + dy * dy
        if d <= m.r * m.r then
            if m.pin then return m end
            if not bestD or d < bestD then best, bestD = m, d end
        end
    end
    return best
end

local function updateHover(off)
    local m = hitTest(off)
    local text
    if m and m.pin then
        text = m.pin.name .. '  (right-click to remove)'
    elseif m then
        text = m.loc.n .. (travelEnabled() and '  (click for options)'
            or (m.track and '  (tracked - click to stop)' or '  (click to track)'))
    end
    hoverText = text
    setHeader(text or defaultHeader())
end

-- ------------------------------------------------------------------ search results UI

local selectResult -- forward

-- Flat list: one background image, then one Text per row (no nesting, and the
-- element is never hidden - it is simply empty when there are no results).
local function renderResults()
    local items = {}
    if #results > 0 then
        items[1] = {
            type = ui.TYPE.Image,
            props = {
                resource = tex(ICONS .. 'white.png'), color = rgb(0.08, 0.06, 0.04), alpha = 0.92,
                size = v2(SEARCH_W, #results * ROW_H + 6),
            },
        }
        for i, loc in ipairs(results) do
            items[#items + 1] = {
                type = ui.TYPE.Text,
                props = {
                    text = loc.n, textSize = 16, position = v2(6, 4 + (i - 1) * ROW_H),
                    textColor = loc.t and COLOR_TEXT_DIM or COLOR_TEXT,
                },
                events = {
                    mousePress = async:callback(function(e)
                        if e.button == 1 then selectResult(loc) end
                    end),
                },
            }
        end
    end
    resultsEl.layout.content = ui.content(items)
    resultsEl:update()
end

selectResult = function(loc)
    local mx, my = worldToMap(loc.x, loc.y)
    center = v2(mx, my)
    clampCenter()
    zoom = math.max(zoom, loc.t and (TOWN_ZOOM + 0.15) or 0.5)
    highlight = { mx = mx, my = my }
    results = {}
    renderResults()
    setHeader(loc.n .. (travelEnabled() and '  (click it for options)' or '  (click it to track)'))
    buildLayer()
end

-- ------------------------------------------------------------------ click popup

-- Flat like the search results: background, button bars, labels, then an
-- invisible full-width image per button that takes the click.
local function closePopup()
    if not popupLoc then return end
    popupLoc = nil
    popupButtons, popupHover = nil, nil
    if visible and not mouseOff then mouseOff = popupAnchor end   -- the cursor is still about here
    if popupEl then
        popupEl.layout.content = ui.content {}
        popupEl.layout.props.size = v2(0, 0)
        popupEl:update()
    end
end

local function openPopup(loc, off)
    popupLoc = loc
    popupAnchor = off
    local blocked = travelBlocked(loc)
    local isTracked = findTracked(locKey(loc)) ~= nil
    local buttons = {
        { label = 'Fast Travel', color = blocked and COLOR_TEXT_DIM or COLOR_TEXT, action = function()
            closePopup()
            local why = travelBlocked(loc)
            if why then ui.showMessage(why) else startTravel(loc) end
        end },
        { label = isTracked and 'Unmark' or 'Mark', color = COLOR_TEXT, action = function()
            closePopup()
            trackLocation(loc)
            buildLayer()
            if mouseOff then updateHover(mouseOff) end
        end },
    }
    popupButtons = buttons
    local w = math.max(170, math.min(380, #loc.n * 8 + 16))
    local h = 28 + #buttons * POPUP_ROW_H + 4
    local x = math.max(2, math.min(off.x + 8, viewSize.x - w - 2))
    local y = math.max(2, math.min(off.y + 8, viewSize.y - h - 2))
    local white = tex(ICONS .. 'white.png')
    local items = {
        { type = ui.TYPE.Image, props = { resource = white, color = rgb(0.08, 0.06, 0.04), alpha = 0.96, size = v2(w, h) } },
        { type = ui.TYPE.Text, props = { text = loc.n, textSize = 15, textColor = COLOR_TEXT_DIM, position = v2(8, 5) } },
    }
    for i, b in ipairs(buttons) do
        local rowY = 28 + (i - 1) * POPUP_ROW_H
        items[#items + 1] = { type = ui.TYPE.Image, props = { resource = white, color = rgb(0.3, 0.24, 0.15),
            alpha = 0.55, position = v2(4, rowY), size = v2(w - 8, POPUP_ROW_H - 3) } }
        items[#items + 1] = { type = ui.TYPE.Text, props = { text = b.label, textSize = 16, textColor = b.color,
            position = v2(12, rowY + 2) } }
        items[#items + 1] = {
            type = ui.TYPE.Image,
            props = { resource = white, alpha = 0, position = v2(4, rowY), size = v2(w - 8, POPUP_ROW_H - 3) },
            events = {
                mousePress = async:callback(function(e)
                    lastMousePressFrame = frameCount
                    if e.button == 1 then b.action() end
                end),
                mouseMove = async:callback(function() popupHover = i end),
                focusGain = async:callback(function() popupHover = i end),
                focusLoss = async:callback(function()
                    if popupHover == i then popupHover = nil end
                end),
            },
        }
    end
    popupEl.layout.props.position = v2(x, y)
    popupEl.layout.props.size = v2(w, h)
    popupEl.layout.content = ui.content(items)
    popupEl:update()
end

-- what a left click on a marker does, by mouse or controller
local function activateMarker(loc, off)
    if travelEnabled() then
        openPopup(loc, off)
    else
        trackLocation(loc)
        buildLayer()
        updateHover(off)
    end
end

-- what a right click does: remove the pin under the cursor, or drop a new one
local function togglePin(off)
    local m = hitTest(off)
    if m and m.pin then
        local i = findTracked(m.pin.key)
        if i then untrack(i, 'Removed ') end
    else
        addPin(mapToWorld(viewToMap(off)))
    end
    buildLayer()
    updateHover(off)
end

-- ------------------------------------------------------------------ window

local function destroyWindow()
    -- nested elements are destroyed explicitly (orphaned elements can crash on reload)
    for _, el in ipairs({ mapLayer, popupEl, resultsEl, header, placeholder }) do
        if el then el:destroy() end
    end
    if root then root:destroy() end
    root, mapLayer, popupEl, resultsEl, header, placeholder = nil, nil, nil, nil, nil, nil
    popupLoc = nil
end

local function createWindow(which)
    local L = LAYOUTS[which]
    local screen = ui.screenSize()
    local W = math.floor(screen.x * L.w)
    local H = math.floor(screen.y * L.h)
    viewSize = v2(W, H - HEADER_H)

    mapLayer = ui.create {
        type = ui.TYPE.Widget,
        props = { size = v2(data.mapWidth * ZOOM_MAX, data.mapHeight * ZOOM_MAX) },
        content = ui.content {},
    }

    popupEl = ui.create {
        type = ui.TYPE.Widget,
        props = { position = v2(0, 0), size = v2(0, 0) },
        content = ui.content {},
    }

    resultsEl = ui.create {
        type = ui.TYPE.Widget,
        props = { position = v2(W - SEARCH_W - 6, HEADER_H), size = v2(SEARCH_W, MAX_RESULTS * ROW_H + 6) },
        content = ui.content {},
    }

    header = ui.create {
        type = ui.TYPE.Text,
        props = { text = 'World Map', textSize = 18, textColor = COLOR_TEXT, position = v2(8, 4) },
    }

    placeholder = ui.create {
        type = ui.TYPE.Text,
        props = { text = 'Search...', textSize = 16, textColor = COLOR_TEXT_DIM,
                  position = v2(W - SEARCH_W, 6), visible = true },
    }

    local searchBox
    searchBox = {
        type = ui.TYPE.TextEdit,
        props = {
            text = '', textSize = 16, textColor = COLOR_TEXT, multiline = false,
            position = v2(W - SEARCH_W - 2, 4), size = v2(SEARCH_W - 6, 20),
        },
        events = {
            textChanged = async:callback(function(text)
                searchText = text
                searchBox.props.text = text   -- keep the layout in sync if the window re-renders
                local empty = (text == '')
                if placeholder.layout.props.visible ~= empty then
                    placeholder.layout.props.visible = empty
                    placeholder:update()
                end
                runSearch(text)
                renderResults()
                if trim(text) ~= '' then
                    setHeader(string.format('%d match%s for "%s"', #results, #results == 1 and '' or 'es', trim(text)))
                end
            end),
            keyPress = async:callback(function(e)
                if e.code == mapKey() then typedM = true end
                if (e.code == input.KEY.Enter or e.code == input.KEY.NP_Enter) and results[1] then
                    selectResult(results[1])
                end
            end),
        },
    }

    local overlay = {
        type = ui.TYPE.Image,
        props = { resource = tex(ICONS .. 'white.png'), alpha = 0, relativeSize = v2(1, 1) },
        events = {
            mousePress = async:callback(function(e)
                lastMousePressFrame = frameCount
                if popupLoc then           -- a click off the popup just closes it
                    closePopup()
                    return
                end
                if e.button == 1 then
                    press = { pos = e.position, center = center, moved = false }
                elseif e.button == 3 then
                    togglePin(e.offset)
                end
            end),
            mouseMove = async:callback(function(e)
                mouseOff = e.offset
                if press then
                    local d = e.position - press.pos
                    if press.moved or d:length() > DRAG_THRESHOLD then
                        press.moved = true
                        center = press.center - d * (1 / zoom)
                        clampCenter()
                        moveLayer()
                    end
                else
                    updateHover(e.offset)
                end
            end),
            focusLoss = async:callback(function()
                mouseOff = nil
            end),
            mouseRelease = async:callback(function(e)
                if not press or e.button ~= 1 then return end
                local wasDrag = press.moved
                press = nil
                if wasDrag then
                    buildLayer()
                else
                    local m = hitTest(e.offset)
                    if m and m.loc then activateMarker(m.loc, e.offset) end
                end
            end),
        },
    }

    local viewport = {
        type = ui.TYPE.Widget,
        props = { position = v2(0, HEADER_H), size = viewSize },
        content = ui.content {
            {
                type = ui.TYPE.Image,
                props = {
                    resource = tex(ICONS .. 'white.png'),
                    color = rgb(data.oceanColor[1], data.oceanColor[2], data.oceanColor[3]),
                    relativeSize = v2(1, 1),
                },
            },
            mapLayer,
            overlay,
            popupEl,
        },
    }

    root = ui.create {
        layer = 'Windows',
        template = I.MWUI.templates.boxSolid,
        props = { relativePosition = L.relativePosition, anchor = L.anchor, visible = false },
        content = ui.content {
            {
                type = ui.TYPE.Widget,
                props = { size = v2(W, H) },
                content = ui.content {
                    header,
                    {
                        type = ui.TYPE.Image,
                        props = {
                            resource = tex(ICONS .. 'white.png'), color = rgb(0, 0, 0), alpha = 0.45,
                            position = v2(W - SEARCH_W - 6, 3), size = v2(SEARCH_W, 22),
                        },
                    },
                    placeholder,
                    searchBox,
                    viewport,
                    resultsEl,
                },
            },
        },
    }
    mode = which
end

local function centerOnPlayer()
    local px, py = playerSpot()
    if px then
        center = v2(worldToMap(px, py))
    elseif not center then
        center = v2(data.mapWidth / 2, data.mapHeight / 2)
    end
    clampCenter()
end

local function show()
    local which = openSolo and 'full' or 'compact'
    openSolo = false
    if root and mode ~= which then destroyWindow() end
    if not root then createWindow(which) end
    visible = true
    press, highlight, hoverText = nil, nil, nil
    results = {}
    renderResults()
    if restoreCenter then                      -- reopened after B closed the popup: same view
        center = restoreCenter
        restoreCenter = nil
        clampCenter()
    else
        centerOnPlayer()
    end
    setHeader(defaultHeader())
    root.layout.props.visible = true
    root:update()
    buildLayer()
end

local function hide()
    if popupLoc then popupHiddenFrame = frameCount end
    closePopup()
    visible = false
    press = nil
    mouseOff = nil
    if root then
        root.layout.props.visible = false
        root:update()
    end
end

I.UI.registerWindow('Map', show, hide)

-- ------------------------------------------------------------------ quest-controlled doors

-- The global script reports which door rules currently hide their doors.
local function onGates(hidden)
    local nextHidden, changed = {}, false
    for _, id in ipairs(hidden) do
        nextHidden[id] = true
        if not hiddenGates[id] then changed = true end
    end
    for id in pairs(hiddenGates) do
        if not nextHidden[id] then changed = true end
    end
    if not changed then return end
    hiddenGates = nextHidden
    for _, loc in ipairs(data.locations) do
        if loc.g and hiddenGates[loc.g] then
            local i = findTracked(locKey(loc))
            if i then untrack(i, 'No longer there: ') end
        end
    end
    if visible then
        closePopup()
        buildLayer()
    end
end

-- ------------------------------------------------------------------ engine handlers

local function zoomTo(z)
    z = math.max(ZOOM_MIN, math.min(ZOOM_MAX, z))
    if z == zoom then return end
    if mouseOff and not press then
        -- keep the map point under the cursor fixed while zooming
        local mx, my = viewToMap(mouseOff)
        zoom = z
        local nx, ny = viewToMap(mouseOff)
        center = v2(center.x + (mx - nx), center.y + (my - ny))
        clampCenter()
    else
        zoom = z
    end
    buildLayer()
    if mouseOff then updateHover(mouseOff) end
end

local function onMouseWheel(vertical)
    if not visible or not vertical or vertical == 0 then return end
    closePopup()
    lastWheelFrame = frameCount
    zoomTo(vertical > 0 and zoom * ZOOM_STEP or zoom / ZOOM_STEP)
end

-- ------------------------------------------------------------------ controller

-- A: press the popup button under the cursor, or select the marker under it
local function padClick()
    if popupLoc then
        local b = popupButtons and popupButtons[popupHover]
        if b then b.action() else closePopup() end
        return
    end
    if not mouseOff then return end
    local m = hitTest(mouseOff)
    if m and m.loc then activateMarker(m.loc, mouseOff) end
end

local function onControllerButtonPress(id)
    local BUTTON = input.CONTROLLER_BUTTON
    if id == mapButton() then
        local current = I.UI.getMode()
        if current == nil then
            openSolo = true
            I.UI.setMode('Interface', { windows = { 'Map' } })
        elseif current == 'Interface' and visible and mode == 'full' then
            I.UI.removeMode('Interface')
        end
        return
    end
    if id == BUTTON.B and (popupLoc or frameCount - popupHiddenFrame <= 2) then
        -- the engine's B also leaves the menu: bring the map straight back if it does
        closePopup()
        keepMap = { solo = mode == 'full', frames = 3, center = center }
        return
    end
    if not visible then return end
    if id == BUTTON.A then
        pendingPadClick = frameCount
    elseif id == BUTTON.X then
        if popupLoc then
            closePopup()
        elseif mouseOff then
            togglePin(mouseOff)
        end
    end
end

-- right stick forward zooms in, back zooms out; paused frames have no game time, so use real time
local function updateStickZoom()
    if press or frameCount - lastWheelFrame < 15 then return end   -- the wheel is in use
    local v = input.getAxisValue(input.CONTROLLER_AXIS.RightY)
    if math.abs(v) < STICK_DEADZONE then
        stickZoomTimer = 0
        return
    end
    stickZoomTimer = stickZoomTimer + core.getRealFrameDuration()
    if stickZoomTimer < STICK_ZOOM_INTERVAL then return end
    local amount = (math.abs(v) - STICK_DEADZONE) / (1 - STICK_DEADZONE)
    local direction = v < 0 and 1 or -1                            -- stick forward reads negative
    closePopup()
    zoomTo(zoom * math.exp(direction * amount * STICK_ZOOM_RATE * stickZoomTimer))
    stickZoomTimer = 0
end

local function updateController()
    if pendingPadClick and frameCount - pendingPadClick >= 2 then
        local pressedAt = pendingPadClick
        pendingPadClick = nil
        -- if the engine turned this press into a mouse click, that click already did the job
        if visible and lastMousePressFrame < pressedAt then padClick() end
    end
    if keepMap then
        keepMap.frames = keepMap.frames - 1
        if not visible and I.UI.getMode() == nil then
            local solo = keepMap.solo
            openSolo, restoreCenter = solo, keepMap.center
            keepMap = nil
            if solo then
                I.UI.setMode('Interface', { windows = { 'Map' } })
            else
                I.UI.setMode('Interface')
            end
        elseif keepMap.frames <= 0 then
            keepMap = nil
        end
    end
    if visible then updateStickZoom() end
end

local function onKeyPress(key)
    if key.code ~= mapKey() then return end
    local current = I.UI.getMode()
    if current == nil then
        openSolo = true
        I.UI.setMode('Interface', { windows = { 'Map' } })
    elseif current == 'Interface' and visible and mode == 'full' then
        -- decide next frame: if the M went into the search box, don't close
        pendingClose = true
    end
end

local function onFrame(dt)
    frameCount = frameCount + 1
    updateController()
    if pendingClose then
        if not typedM and visible then I.UI.removeMode('Interface') end
        pendingClose = false
    end
    typedM = false

    local cell = self.cell
    if cell and cell.isExterior then
        local p = self.position
        lastExterior = { x = p.x, y = p.y, yaw = self.rotation:getYaw() }
    end

    clearCheckTimer = clearCheckTimer + (dt or 0)
    if clearCheckTimer > 0.5 then
        clearCheckTimer = 0
        recordVisit()
        checkReached()
    end
end

local function onSave()
    return { lastExterior = lastExterior, zoom = zoom, tracked = tracked, pinCounter = pinCounter,
             visited = visited }
end

local function onLoad(saved)
    if saved then
        lastExterior = saved.lastExterior
        zoom = saved.zoom or zoom
        tracked = saved.tracked or {}
        pinCounter = saved.pinCounter or 0
        visited = saved.visited or {}
    end
end

return {
    interfaceName = 'NGLA',
    interface = {
        version = 1,
        -- For the compass (and other mods): a copy of the tracked destinations.
        -- Each entry: {name, x, y, pin, color = util.color}
        getTracked = function()
            local out = {}
            for i, t in ipairs(tracked) do
                out[i] = { name = t.name, x = t.x, y = t.y, pin = t.pin or false,
                           color = TRACK_COLORS[t.color] or TRACK_COLORS[1] }
            end
            return out
        end,
    },
    engineHandlers = {
        onMouseWheel = onMouseWheel,
        onKeyPress = onKeyPress,
        onControllerButtonPress = onControllerButtonPress,
        onFrame = onFrame,
        onUpdate = onUpdate,
        onSave = onSave,
        onLoad = onLoad,
    },
    eventHandlers = {
        NGLA_SurveyReply = onSurveyReply,
        NGLA_Gates = onGates,
    },
}
