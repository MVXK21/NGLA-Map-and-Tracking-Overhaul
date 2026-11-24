-- NGLA Map and Tracking Overhaul: lets fast travel ask nearby actors whether
-- they are attacking the player or following them. Does nothing until asked.

local self = require('openmw.self')
local types = require('openmw.types')
local I = require('openmw.interfaces')

local function hasTarget(packageType, player)
    for _, target in ipairs(I.AI.getTargets(packageType)) do
        if target == player then return true end
    end
    return false
end

local function survey(player)
    if types.Actor.isDead(self.object) then return end
    local hostile = hasTarget('Combat', player)
    local active = I.AI.getActivePackage()
    local waiting = active and (active.type == 'Wander' or active.type == 'Travel')  -- told to stay put
    local follower = not waiting and (hasTarget('Follow', player) or hasTarget('Escort', player))
    if hostile or follower then
        player:sendEvent('NGLA_SurveyReply', { actor = self.object, hostile = hostile, follower = follower })
    end
end

return {
    eventHandlers = { NGLA_Survey = survey },
}
