import melee
import globals
import Chains
import math
from melee.enums import Action, Button
from Tactics.tactic import Tactic
from Chains.smashattack import SMASH_DIRECTION

class Punish(Tactic):
    # How many frames do we have to work with for the punish
    def framesleft():
        opponent_state = globals.opponent_state

        # For some dumb reason, the game shows the standing animation as having a large hitstun
        #   manually account for this
        if opponent_state == Action.STANDING:
            return 1

        # Is opponent attacking?
        if globals.framedata.isattack(opponent_state.character, opponent_state.action):
            # What state of the attack is the opponent in?
            # Windup / Attacking / Cooldown
            attackstate = globals.framedata.attackstate_simple(opponent_state)
            if attackstate == melee.enums.AttackState.WINDUP:
                frame = globals.framedata.firsthitboxframe(opponent_state.character, opponent_state.action)
                return max(0, frame - opponent_state.action_frame)
            if attackstate == melee.enums.AttackState.ATTACKING:
                return 0
            if attackstate == melee.enums.AttackState.COOLDOWN:
                frame = globals.framedata.iasa(opponent_state.character, opponent_state.action)
                return max(0, frame - opponent_state.action_frame)
        if globals.framedata.isroll(opponent_state.character, opponent_state.action):
            frame = globals.framedata.lastrollframe(opponent_state.character, opponent_state.action)
            return max(0, frame - opponent_state.action_frame)

        # Opponent is in hitstun
        if opponent_state.hitstun_frames_left > 0:
            # Special case here for lying on the ground.
            #   For some reason, the hitstun count is totally wrong for these actions
            if opponent_state.action in [Action.LYING_GROUND_UP, Action.LYING_GROUND_DOWN]:
                return 1
            return opponent_state.hitstun_frames_left
        return 1

    # Static function that returns whether we have enough time to run in and punish,
    # given the current gamestate. Either a shine or upsmash
    def canpunish():
        opponent_state = globals.opponent_state

        # Can't punish opponent in shield
        shieldactions = [Action.SHIELD_START, Action.SHIELD, Action.SHIELD_RELEASE, \
            Action.SHIELD_STUN, Action.SHIELD_REFLECT]
        if opponent_state.action in shieldactions:
            return False

        left = Punish.framesleft()
        # Will our opponent be invulnerable for the entire punishable window?
        if left <= opponent_state.invulnerability_left:
            return False

        if left < 1:
            return False

        if globals.framedata.isroll(opponent_state.character, opponent_state.action):
            return True

        # Can we shine right now without any movement?
        shineablestates = [Action.TURNING, Action.STANDING, Action.WALK_SLOW, Action.WALK_MIDDLE, \
            Action.WALK_FAST, Action.EDGE_TEETERING_START, Action.EDGE_TEETERING, Action.CROUCHING, \
            Action.RUNNING]

        #TODO: Wrap the shine range into a helper
        foxshinerange = 11.8
        inshinerange = globals.gamestate.distance < foxshinerange

        if inshinerange and globals.smashbot_state.action in shineablestates:
            return True

        #TODO: Wrap this up into a helper
        foxrunspeed = 2.2
        #TODO: Subtract from this time spent turning or transitioning
        # Assume that we can run at max speed toward our opponent
        # We can only run for framesleft-1 frames, since we have to spend at least one attacking
        potentialrundistance = (left-1) * foxrunspeed

        if globals.gamestate.distance - potentialrundistance < foxshinerange:
            return True
        return False

    def step(self):
        smashbot_state = globals.smashbot_state
        opponent_state = globals.opponent_state
        #If we can't interrupt the chain, just continue it
        if self.chain != None and not self.chain.interruptible:
            self.chain.step()
            return

        # TODO: This should be all inactionalbe animations, actually
        if smashbot_state.action == Action.THROW_DOWN:
            self.pickchain(Chains.Nothing)
            return

        # Can we charge an upsmash right now?
        framesleft = Punish.framesleft()
        if globals.logger:
            globals.logger.log("Notes", "framesleft: " + str(framesleft) + " ", concat=True)

        # How many frames do we need for an upsmash?
        # It's 7 frames normally, plus some transition frames
        # 3 if in shield, shine, or dash/running
        framesneeded = 7
        shieldactions = [Action.SHIELD_START, Action.SHIELD, Action.SHIELD_RELEASE, \
            Action.SHIELD_STUN, Action.SHIELD_REFLECT]
        shineactions = [Action.DOWN_B_STUN, Action.DOWN_B_GROUND_START, Action.DOWN_B_GROUND]
        runningactions = [Action.DASHING, Action.RUNNING]
        if smashbot_state.action in shieldactions:
            framesneeded += 3
        if smashbot_state.action in shineactions:
            framesneeded += 3
        if smashbot_state.action in runningactions:
            framesneeded += 3

        endposition = opponent_state.x
        isroll = globals.framedata.isroll(opponent_state.character, opponent_state.action)

        # If we have the time....
        if framesneeded < framesleft:
            # Calculate where the opponent will end up
            if opponent_state.hitstun_frames_left > 0:
                endposition = opponent_state.x + globals.framedata.slidedistance(opponent_state.character, opponent_state.speed_x_attack, framesleft)

            if isroll:
                endposition = globals.framedata.endrollposition(opponent_state, globals.gamestate.stage)
                endposition += globals.framedata.slidedistance(opponent_state.character, opponent_state.speed_x_attack + opponent_state.speed_ground_x_self, framesleft)
                # But don't go off the end of the stage
                endposition = max(endposition, -melee.stages.edgegroundposition(globals.gamestate.stage))
                endposition = min(endposition, melee.stages.edgegroundposition(globals.gamestate.stage))

            # And we're in range...
            # Take our sliding into account
            slidedistance = globals.framedata.slidedistance(smashbot_state.character, smashbot_state.speed_ground_x_self, framesleft)
            smashbot_endposition = slidedistance + smashbot_state.x


            # Do we have to consider character pushing?
            # Are we between the character's current and predicted position?
            if abs(opponent_state.x) < abs(smashbot_endposition) and abs(smashbot_endposition) < abs(endposition):
                # Add a little bit of push distance along that path
                # 0.3 pushing for max of 16 frames
                onleft = smashbot_state.x < opponent_state.x
                if onleft:
                    smashbot_endposition -= 4.8
                else:
                    smashbot_endposition += 4.8

            facing = smashbot_state.facing == (smashbot_endposition < endposition)
            # Remember that if we're turning, the attack will come out the opposite way
            if smashbot_state.action == Action.TURNING:
                facing = not facing
            distance = abs(endposition - smashbot_endposition)
            if distance < 14.5 and facing:
                # Do the upsmash
                # NOTE: If we get here, we want to delete the chain and start over
                #   Since the amount we need to charge may have changed
                self.chain = None
                self.pickchain(Chains.SmashAttack, [framesleft-framesneeded-1, SMASH_DIRECTION.UP])
                return
            # If we're not in attack range, and can't run, then maybe we can wavedash in
            #   Now we need more time for the wavedash. 10 frames of lag, and 3 jumping
            framesneeded = 13
            if framesneeded < framesleft:
                if smashbot_state.action in shieldactions or smashbot_state.action in shineactions:
                    self.pickchain(Chains.Wavedash)
                    return

        # We can't smash our opponent, so let's just shine instead. Do we have time for that?
        #TODO: Wrap the shine range into a helper
        framesneeded = 1
        if smashbot_state.action == Action.DASHING:
            framesneeded = 2
        foxshinerange = 11.8
        if globals.gamestate.distance < foxshinerange and (framesneeded < framesleft):
            # Also, don't shine someone in the middle of a roll
            if (not isroll) or (opponent_state.action_frame < 3):
                self.chain = None
                self.pickchain(Chains.Waveshine)
                return

        # Kill the existing chain and start a new one
        self.chain = None
        self.pickchain(Chains.DashDance, [endposition])
