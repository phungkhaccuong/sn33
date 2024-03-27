verbose = False

import copy
import random
import asyncio
import math

from conversationgenome.Utils import Utils
from conversationgenome.MinerLib import MinerLib
from conversationgenome.ConvoLib import ConvoLib
from conversationgenome.LlmLib import LlmLib
from conversationgenome.ConfigLib import c
from conversationgenome.MockBt import MockBt

bt = None
try:
    import bittensor as bt
except:
    if verbose:
        print("bittensor not installed")
    bt = MockBt()

proto = {
    "interests_of_q": [],
    "hobbies_of_q": [],
    "personality_traits_of_q": [],
    "interests_of_a": [],
    "hobbies_of_a": [],
    "personality_traits_of_a": [],
}


class ValidatorLib:
    hotkey = "v1234"

    async def calculate_base_score(self, result_dict):
        total_1 = result_dict['total_1']
        total_2 = result_dict['total_2']
        unique_1_count = len(result_dict['unique_1'])
        unique_2_count = len(result_dict['unique_2'])
        both_count = len(result_dict['both'])

        # If all elements match, return a very low score
        if unique_1_count == 0 and unique_2_count == 0:
            return 0.1

        # If a large percentage of array 2 is unique, return a low score
        unique_2_ratio = unique_2_count / total_2
        if unique_2_ratio > 0.5:
            return 0.2

        # Calculate the percentage of matches
        matches_ratio = both_count / max(total_1, total_2)

        # Calculate the percentage of desired unique elements in array 2
        desired_unique_ratio = min(unique_2_count / (total_1 + unique_2_count), 0.2)

        # Combine the two ratios to get the final score
        score = (matches_ratio * 0.8) + (desired_unique_ratio * 0.2)

        return score

    async def calculate_emission_rewards(self, dicts, scoreKey):
        scores = Utils.pluck(dicts, scoreKey)
        total_scores = sum(scores)
        mean = total_scores / len(scores)
        stdev = math.sqrt(sum((x - mean) ** 2 for x in scores) / len(scores))

        def normal_pdf(x, mean, stdev):
            return math.exp(-(x - mean) ** 2 / (2 * stdev ** 2)) / (stdev * math.sqrt(2 * math.pi))

        rewards = []
        for cur_dict in dicts:
            score = Utils.get(cur_dict, scoreKey)
            pdf_value = normal_pdf(score, mean, stdev)
            reward_percentage = pdf_value / sum(normal_pdf(x, mean, stdev) for x in scores)
            cur_dict['reward'] = reward_percentage
            rewards.append(reward_percentage)

        return rewards

    async def requestConvo(self):
        minConvWindows = 1
        hotkey = "a123"
        fullConvo = await self.getConvo(hotkey)
        #print("fullConvo", fullConvo)

        if fullConvo:
            # Do overview tagging and participant profiles
            fullConvoMetaData = await self.generateFullConvoMetaData(fullConvo)
            #print("fullConvoMetaData", fullConvoMetaData)
            participantProfiles = Utils.get(fullConvoMetaData, "participantProfiles", [])
            fullConvoTags = Utils.get(fullConvoMetaData, "tags", [])
            fullConvoTagVectors = Utils.get(fullConvoMetaData, "tag_vectors", {})

            # Make sure there are enough tags to make processing worthwhile
            minValidTags = self.validateMinimumTags(fullConvoTags)
            if minValidTags:
                convoWindows = self.getConvoWindows(fullConvo)
                numWindows = len(convoWindows)
                if numWindows > minConvWindows:
                    print("Found %d convo windows. Sending to miners..." % (numWindows))
                    await self.sendWindowsToMiners(fullConvoTags, convoWindows, fullConvo)
                else:
                    print("Not enough convo windows -- only %d. Passing." % (numWindows))
            else:
                print("Not enough valid tags for conversation. Passing.")
                return

    async def eventLoop(self):
        while True:
            await self.requestConvo()

    async def getConvo(self, hotkey):
        cl = ConvoLib()
        convo = await cl.getConversation(hotkey, dryrun=True)
        return convo

    def getConvoWindows(self, fullConvo):
        minLines = c.get("convo_window", "min_lines", 5)
        maxLines = c.get("convo_window", "max_lines", 10)
        overlapLines = c.get("convo_window", "overlap_lines", 2)

        windows = Utils.split_overlap_array(fullConvo['lines'], size=maxLines, overlap=overlapLines)
        if len(windows) < 2:
            windows = Utils.split_overlap_array(fullConvo['lines'], size=minLines, overlap=overlapLines)

        # TODO: Write convo windows into local database with full convo metadata
        return windows



    async def generateFullConvoMetaData(self, convo):
        cl = ConvoLib()
        #print("METACONVO participants", convo['participants'])

        llml = LlmLib()
        matches_dict = await llml.conversation_to_tags(convo)
        tags = list(matches_dict.keys())

        half = int(len(tags) / 2)
        tagsQ = tags[0:half]
        tagsA = tags[half:]
        info = copy.deepcopy(proto)
        #info["interests_of_q"] = tagsQ
        #info["interests_of_a"] = tagsA
        ##print("FullConvo tags",  tags)
        print("Found %d FullConvo tags" % len(tags) )
        data = {
            "participantProfiles": convo['participants'],
            "tags": tags,
            "tag_vectors": matches_dict,
        }
        return data

    async def sendToMiners(self, convoWindow, minerUids):
        print("Send to miners", minerUids)
        results = []
        ml = MinerLib()
        tasks = [asyncio.create_task(ml.doMining(convoWindow, minerUid)) for minerUid in minerUids]
        await asyncio.wait(tasks)
        for task in tasks:
            results.append(task.result())
        return results

    def score(self):
        pass

    def validate_tags(self, tags):
        print("validate_tags")
        return True

    def validateMinimumTags(self, tags):
        return True

    def selectStage1Miners(self, uids, num=3):
        selectedMiners = random.sample(uids, num)
        return selectedMiners

    async def outputEmissions(self, convoId, windowId, emissionRewards):
        print("EMISSIONS for %d window %d" % (convoId, windowId), emissionRewards)


    async def sendWindowsToMiners(self, fullConvoTags, windows, fullConvo=None):
        cguid = Utils.get(fullConvo, "uid")
        # Get uids of available miners
        uids = bt.getUids()
        if len(uids) < 6:
            print("Not enough miners available.")
            return

        print("Full convo tags", fullConvoTags)

        # Loop through rows in db
        success = True
        for idx, window in enumerate(windows):
            # Pick initial minors
            miners = self.selectStage1Miners(uids, 5)
            # Send first window to 3 miners
            minerResults = await self.sendToMiners(window, miners)
            # Each miner returns data, write data into local db
            #print("Miner results", minerResults)
            # TODO: Write up incomplete errors, such as if timeout happens for miner, send to another miner
            # When all miners have returned data for convo window
            for minerResult in minerResults:
                uid = Utils.get(minerResult, 'uid')
                tags = Utils.get(minerResult, 'tags')
                compareResults = Utils.compare_arrays(fullConvoTags, tags)
                compareResults['total_1'] = len(fullConvoTags)
                compareResults['total_2'] = len(tags)
                #print("COMPARE", compareResults)
                scoreToFullConvo = await self.calculate_base_score(compareResults)
                minerResult['score'] = scoreToFullConvo

            await self.calculate_emission_rewards(minerResults, 'score')
            rewards = {}
            for minerResult in minerResults:
                rewards[minerResult['uid']] = minerResult['reward']
            # Send emissions
            await self.outputEmissions(1, idx, rewards)
        if success == True:
            cl = ConvoLib()
            await cl.markConversionComplete(self.hotkey, cguid)

