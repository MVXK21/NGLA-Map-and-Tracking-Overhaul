-- NGLA Map and Tracking Overhaul: performs fast travel.
-- Teleporting and advancing time are only allowed from a global script; the
-- map (a player script) has already checked the restrictions.
-- Also reports which quest-controlled doors currently exist: global variables
-- can only be read from here.

local util = require('openmw.util')
local world = require('openmw.world')
local types = require('openmw.types')

local gates = require('scripts.NGLA.generated.gates')

local GATE_INTERVAL = 1           -- seconds between checks
local RESEND_EVERY = 5            -- checks between sends, even if nothing changed

local function fastTravel(d)
    local cell = d.cell or ''
    local pos = util.vector3(d.x, d.y, d.z)
    local rotation = util.transform.rotateZ(d.rot)
    d.player:teleport(cell, pos, { rotation = rotation, onGround = d.ground })

    -- companions arrive just ahead of the player, spread sideways (arrival
    -- points face away from their door, so ahead is the open side)
    local forward = util.vector3(math.sin(d.rot), math.cos(d.rot), 0)
    local side = util.vector3(forward.y, -forward.x, 0)
    for i, actor in ipairs(d.followers or {}) do
        if actor:isValid() then
            local spread = (i - (#d.followers + 1) / 2) * 70
            actor:teleport(cell, pos + forward * 100 + side * spread, { rotation = rotation, onGround = true })
        end
    end

    if d.hours and d.hours > 0 then world.advanceTime(d.hours) end
end

-- ------------------------------------------------------------------ quest-controlled doors

local COMPARE = {
    ['=='] = function(a, b) return a == b end,
    ['!='] = function(a, b) return a ~= b end,
    ['<'] = function(a, b) return a < b end,
    ['<='] = function(a, b) return a <= b end,
    ['>'] = function(a, b) return a > b end,
    ['>='] = function(a, b) return a >= b end,
}

-- current value of a condition's variable, or nil if the game doesn't have it
local function readValue(kind, name, player, globals)
    local ok, value
    if kind == 'g' then
        ok, value = pcall(function() return globals[name] end)
    else
        ok, value = pcall(function()
            local quest = types.Player.quests(player)[name]
            return quest and quest.stage or 0
        end)
    end
    if ok then return value end
    return nil
end

-- true / false, or nil if a value couldn't be read (the door then stays on the map)
local function ruleHolds(rule, player, globals)
    for _, c in ipairs(rule.c) do
        local value = readValue(c[1], c[2], player, globals)
        if value == nil then return nil end
        if not COMPARE[c[3]](value, c[4]) then return false end
    end
    return true
end

local function gateVisible(rules, player, globals)
    local isVisible = true
    for _, rule in ipairs(rules) do
        local holds = ruleHolds(rule, player, globals)
        if holds == nil then return true end
        if holds then
            if rule.v ~= nil then isVisible = rule.v end
            if rule.s then break end
        end
    end
    return isVisible
end

local gateTimer, sendCounter, lastSent = GATE_INTERVAL, 0, nil

local function onUpdate(dt)
    gateTimer = gateTimer + dt
    if gateTimer < GATE_INTERVAL then return end
    gateTimer = 0
    local player = world.players[1]
    if not player then return end
    local globals = world.mwscript.getGlobalVariables(player)
    local hidden = {}
    for id, rules in ipairs(gates.rules) do
        if not gateVisible(rules, player, globals) then hidden[#hidden + 1] = id end
    end
    local key = table.concat(hidden, ',')
    sendCounter = sendCounter + 1
    if key ~= lastSent or sendCounter >= RESEND_EVERY then   -- resend: the player script may have just reloaded
        lastSent, sendCounter = key, 0
        player:sendEvent('NGLA_Gates', hidden)
    end
end

return {
    engineHandlers = { onUpdate = onUpdate },
    eventHandlers = { NGLA_FastTravel = fastTravel },
}
