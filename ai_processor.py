import requests
import os
import re
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class AIOutput:
    article: dict
    notes: dict


PROMPT_TEMPLATE = """
    VERY IMPORTANT: Respond with EXACTLY ONE JSON object. No text before or after. No markdown.

    JSON structure:
    {{
        "article": {{
            "title": string,
            "sections": [
                {{
                    "heading": string,
                    "content": string
                }}
            ]
        }},
        "notes": {{
            "topics": [
                {{
                    "topic": string,
                    "points": [string]
                }}
            ]
        }}
    }}

    You are an expert educator, technical writer, and curriculum designer.

    Your task is to transform a transcript into a complete educational resource.

    IMPORTANT:
    This is NOT a summarization task.
    The goal is to preserve the knowledge, reasoning, and teaching value of the transcript.

    The output should allow a beginner to learn the topic without needing to watch the original transcript.

    PROCESSING RULES:
    Before writing:
    1. Identify the main concepts, ideas, and learning objectives.
    2. Identify definitions, explanations, examples, demonstrations, comparisons, and step-by-step processes.
    3. Organize the information into a logical teaching structure.
    4. Rewrite the transcript into a polished educational article.

    ARTICLE REQUIREMENTS:
    - Preserve the majority of meaningful instructional content from the transcript.
    - Do not aggressively shorten or compress explanations.
    - Keep important terminology and concepts.
    - Preserve the relationship between ideas, including:
        - why something works
        - how something works
        - when something should be used
        - advantages and limitations
        - examples or practical applications
    - If the speaker explains a concept over several sentences, keep that explanation rather than reducing it to a single statement.
    - If the speaker introduces a problem, process, solution, or conclusion, preserve the full chain of reasoning.
    - Expand structure with headings and paragraphs when needed.
    - Remove only:
        - greetings and introductions unrelated to the topic
        - filler words
        - verbal mistakes
        - repeated statements
        - off-topic conversation

    Do not convert explanations into bullet-point summaries.
    Do not replace detailed explanations with vague statements.

    The article should read like:
    - a textbook chapter
    - a technical blog post
    - a course lesson

    It should NOT read like:
    - lecture notes
    - a short summary
    - a list of key points

    LENGTH REQUIREMENT:
    The article should normally retain approximately 60-90% of the original educational content after removing filler and repetition.
    If the transcript contains many explanations or examples, prioritize completeness over brevity.

    NOTES REQUIREMENTS:
    Create separate study notes for review:
    - Capture important terms, concepts, relationships, commands, formulas, processes, or facts.
    - Keep notes concise.
    - Notes should complement the article, not replace it.

    ACCURACY:
    - Do not invent information that is not supported by the transcript.
    - Do not add unrelated background knowledge.
    - If clarification is needed, explain using only the context available in the transcript.

    Transcript:
    {transcript}
""".strip()


class AIProcessor(ABC):
    def __init__(self, model: str, temperature: float = 0.2):
        self.model = model
        self.temperature = temperature

    def _build_prompt(self, transcript: str) -> str:
        return PROMPT_TEMPLATE.format(transcript=transcript)

    @abstractmethod
    def _call_model(self, prompt: str) -> str: ...

    def _parse(self, raw: str) -> AIOutput:
        cleaned = re.sub(r"```json\s*|\s*```", "", raw).strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ValueError(f"Model did not return valid JSON: {e}\nRaw output:\n{raw}")

        try:
            return AIOutput(article=data["article"], notes=data["notes"])
        except KeyError as e:
            raise ValueError(f"Missing expected key in model output: {e}\nParsed data:\n{data}")

    def convert(self, transcript: str) -> AIOutput:
        prompt = self._build_prompt(transcript)
        print("Processing transcript...")
        raw = self._call_model(prompt)
        print("Model response:", raw)
        return self._parse(raw)


class OllamaAIProcessor(AIProcessor):
    def __init__(
        self,
        model: str = "llama3.1:8b",
        temperature: float = 0.2,
        url: str = "http://localhost:11434/api/generate",
    ):
        super().__init__(model=model, temperature=temperature)
        self.url = url

    def _call_model(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": self.temperature,
                "num_ctx": 8192,
                "num_predict": 4096,
            },
        }
        response = requests.post(self.url, json=payload)
        response.raise_for_status()
        return response.json()["response"].strip()


class OpenAIAIProcessor(AIProcessor):
    def __init__(
        self,
        model: str = "gpt-4o-mini",
        temperature: float = 0.2,
    ):
        super().__init__(model=model, temperature=temperature)
        self.api_key = os.environ["OPENAI_API_KEY"]
        self.url = "https://api.openai.com/v1/chat/completions"

    def _call_model(self, prompt: str) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": prompt}],
        }
        response = requests.post(self.url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


class GeminiAIProcessor(AIProcessor):
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(
        self,
        model: str = "gemini-3.5-flash",
        temperature: float = 0.2,
        maxOutputTokens: int = 20000,
    ):
        super().__init__(model=model, temperature=temperature)
        self.api_key = os.environ["GEMINI_API_KEY"]

    def _call_model(self, prompt: str) -> str:
        url = f"{self.BASE_URL}/{self.model}:generateContent"
        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": self.temperature,
                "responseMimeType": "application/json",
            },
        }
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()["candidates"][0]["content"]["parts"][0]["text"]


if __name__ == "__main__":
    # Swap processors here to test different providers
    processor = GeminiAIProcessor()
    # processor = OllamaAIProcessor()

    TRANSCRIPT = "Thank you. I'm a big fan for making things simple. And in the past, when you started to take a look at wide area networking where you would have to join multiple networks together, it was a challenge. And there was a lot of work that had to go in to building resources like gateway services. Now we do still have those, we'll be doing those in another recording, but I'm a big fan, as I said, making things simple. And we're gonna hopefully show you how simple this is using a feature called VNet peering. My name is Bob Tickleman, and I'm excited to be your guide for this module, let's get into it. VNet peering as a service with inside of Azure networking is a very simple way to take multiple virtual networks or VNets and having them communicate together by literally just touching them together, joining them together and doing a small amount of configuration is going to replace hours of work. And so we're gonna take a look at what VNet peering is. We wanna take a look at how we get what is called gateway transit and get this complex networking capability with a very simple tool to implement it. This service has evolved over time. And what we used to have in the early days for about the first almost eight years was we had a feature called VNet peering, which you're seeing here on the right hand part of the slide. The ability to join two VNets together in the same region. So if you had the resources deployed in say, US West, it was easy to do this in this very simple method. But if they were across multiple regions inside of Azure, you had to do the traditional manner of doing this where you would have to create a VPN gateway to send that traffic out. You would connect through the public internet to connect to a VPN gateway at the other region to have it be inbound. Now that added cost, it added administration, it added traffic going across a wide area network. I had added a whole bunch of stuff to this. And several years ago, they were able to extend the feature of VNet peering that we had within the region. We called it regional VNet peering now. And we had the capability of using what we refer to as the backbone of Azure. So using the networking services of Azure, you can now communicate internally to the software defined network environment of Azure and use its address spaces to communicate across all the Azure regions. Now, when I go to the whiteboard, I'm gonna show you what that means. And when you build these networks, you're gonna be given the choice to be using Microsoft routing or public routing that you have, but you can have different configurations. But great feature to be able to make this very, very simple. But what it does is it very simply builds the networking infrastructure of these gateway devices, and you don't have to pay for them. There's no additional costs where in the past, if I were to build these two VPN gateways, there was a cost that was involved with this to have them up and running. So significant improvement from ease and performance as well as cost. I'm gonna be doing some whiteboarding in a minute with just these two networks, but what you wanna find is this capability in getting into a hub and spoke. And I've used this term a couple of times in other recordings. Now, this is also going to a new service where you take a look at WAN or virtual networks across a wide area network, and we've got V-WAN capabilities. We're not gonna get into it in this module or in this series of recordings at all, but it might be something you wanna take a look at to be able to say, how do I not just do this within a region? I wanna do it on a global basis, and I wanna have these capabilities maybe even back to the on-premises world. So take a look at maybe a future recording on WAN connectivity using Azure services. We're gonna take a look at it from the existing environment using VNets as well as VNet peering. So in this model, we have three VNets. We've got VNet A in the top left, VNet B in the top right, our spokes, and we have our hub network in VNet hub. By default, VNets don't talk to each other. Now, we saw that a VNet by default could have multiple subnets, and so I could have multiple subnets. Maybe this one is gonna be going in my example, 10.1.1.0.24. I've got this one at 10.1.2.0.24. Could have a third one here, 10.1.3.0.24. By default, they all communicated. We saw that in another recording. What I can now do through a VNet peer is by simply touching this VNet, touching, by connecting it through a software definition of the VNet peer, it allows all the subnets in VNet A to talk to all of the subnets, in this case, the hub network. So very simple, and now they all can communicate. This is also where you may want to start working with and in another recording, we took a look at things called NSGs, or the network security groups. Now, I'm gonna refer to this as it said A, B, I'm gonna refer to this as C. VNet peering, and this is an important concept, is non-transitive, because A trusts C, and C trusts B, it does not mean that A can communicate with B by default. So in this model, where A is paired with, in this case, C, and B is also paired, by default, these two cannot communicate with each other. Now, there's several ways that we'll take a look at how we could make that happen, and this is where we're gonna get these things called gateway subnets to be able to do this. You'll see this come across, but by default, I wanna set that up to the start, and I could create a peer here to make that work, and so now everybody talks to everybody, but this does not scale. You really still wanna think at a hub and spoke model, because if I add another VNet, call this VNet three, and I peered this, now I have to peer it with this one, and this one, now it starts getting, if I add another one, I have to peer it with this one, this one, that one, and this one, it does not scale, and having a hub and spoke is truly the best network way to be able to do this. VNet peering is a capability to be able to take two VNets and through that peer. Now, in fact, it's two one-way pairs, and this isn't obvious when we're gonna create this in the demonstration. It is a peer that goes from VNet A to hub, and from hub back to VNet A. Now, I'm gonna be using a user account that has the permissions to all the subscription and all the resources to be able to do this in both locations. We don't talk about much in the books or the content, but realize that this could be secured, that you might need two people to work together to do this, but the tool that I'm gonna be using to do this, it's gonna create both of these at the same time. It's gonna look like it's a single connection, but in fact, it's two names, and what you wanna end up having is a name that says A2, in this case, C, and you want the other name C2A. Common mistake that customers will often see is I'll go in and take a look at it, and they use the same name for both of them when they're built in the graphical interface that they didn't understand, and so this one is called A2C, but in fact, it's the other way around, and again, I'll demonstrate that when I get into the lab environment. So VNet peering, and provides this gateway transit capability, as I said, by default, A can't talk to B, but what I can now have is I can build a gateway subnet, and I can allow for, and it's one of the attributes on the peer itself, to say do I allow the gateway to be a transit, so then I can go to a gateway, or a thing in this case, maybe the NVA, the network virtual appliance, so that it could route that traffic off to B, so you can get them to work, and communicate through the gateway network, as opposed to having to work with other VNet peers that you're gonna peer the network specifically. The other thing that you're working with is this gateway might give you access to some public access through the internet, and so I could then share this gateway network without having to build gateways, because there's a cost, in each of these subnets to get to the internet, they could actually go to the gateway subnet, and be able to use that gateway service to be able to get to an on-premises environment through a VPN, or public access to those resources. When I get into the demonstration, you're gonna see, as I said, these are two different connections made at the same time, and this is where you get into the peer link name, you'll see this when I get into it, you wanna make sure that you're switching them around, and in the same graphical interface, they make it look like there's two different screens here, it's one screen, they're stacked on top of each other, and if you're not paying attention, the remote network is two, connecting to one, the local network is one, but we're connecting back to two. Inside of each of these, we have a series of configuration features that says, do I allow VNet2 to access VNet1, yes or no? You'll see it's on by default, and that's the only one. Allow VNet2 to receive forwarded traffic from VNet1. So again, if we're gonna go through the VNet hub, I'm gonna take traffic from VNet1, in our case, through the hub network, and it's gonna then forward it off to VNet2, so am I gonna accept VNet1 traffic through to VNet2 here, through a forwarding component that you're working with? So there's different configuration values, you typically want them to be the same in both directions, but they don't have to be. My big point on this slide is, they are not one configuration, they are two one-way communications built at the same time. The term is called service chaining, but you'll often see this capability, and it goes back to the diagram that we had, I can have in the hub network, and then actually go back to a slide just a few minutes ago, because I think it displays this better. So what I can now do, through a set of routes, and we're gonna take a look at the term, I've used it in other recordings, there is a system-defined route between all the subnets in a VNet. Remember, all subnets in a VNet can talk to each other by default. When I peer two VNets together, all the subnets on this VNet can talk to all the subnets on this VNet, that's great. But what happens is, I wanna be able to now transmit the information from subnet one to a network virtual appliance, and then have that go off to subnet number two. So that is what they're calling service chaining, so I don't have to provide a peer specifically. I send any traffic, so if you were to take a look at the system-defined route, I can say, hey, you're looking to get to the 10.2 network, .0.0, forward slash 16, should put that line in there. If you're looking for that network, you get a user-defined route that will send it, say, send it to the IP address of the NVA, the NVA will then have the system-defined route that will then say, oh, you're looking for that subnet, go to this one here to get that. So that's what you're working off with that service chaining. So not a new topic from networking perspective, but we can support it using the VNets itself. So let's go take a look at this and see what it looks like. So what I have is I've got four VNets, three of them are in West US three, and I've got one in West Europe. I've got them configured as spoke one, spoke two in the same region, I've got a hub in West US, and I've got a global VNet peer which is three. So those four VNets currently can't speak to each other. So I'm gonna go in and show you, all four of them are standalone VNets, and if I were to have devices in them, I would try and ping them, but I'm not gonna just from a timing perspective, do all of that to prove it to you, but hopefully you can believe me. So I'm gonna come into peering. So I'm here in spoke two, it has no peers. Back to the resource group, I'm gonna come into spoke one, come into its peers, don't have anything. I'm gonna come back into the hub. So all these three are in the same region, peering, don't have anything. And then I'm gonna go to my West Europe, and I'll come into its peers, and it doesn't have anything. So there's no communications, we have four separate standalones, and I'm gonna come to the hub, and I'm gonna create spokes into spoke one and spoke two. I'm gonna do it from hub, I'm gonna do them two different ways, I'm gonna do them correctly with the right naming, I'm gonna show you another one where I do them incorrectly, where I use the same name for both directions, and hopefully that will articulate the potential confusion. So I'm gonna come into the hub, and where you do this from, it doesn't really matter, as long as you have permissions to be able to do this. So I'm gonna come into my peering, and so I'm in the hub network, and I'm gonna add a peer, and I'm gonna come from spoke one to the hub. Because this is the remote virtual network, I'm actually going to that one and bringing that communication here. I can do it for the entire VNet, or just a specific subnet. I have a subscription, they're all on the same subscription, so this is gonna come from spoke one. I have these features of, do I allow spoke one to be able to access the stuff on hub? Yes, and do I want spoke one to allow and receive traffic from hub one? So I'm gonna say yes there. Now this is from the local network, so this one is from hub to spoke one. So it's the reverse of this one. So it's from this network to the spoke. This will just take a second. So I've got from hub to spoke one. I'm in hub. I'm gonna go to spoke one now. And see its peers. And this is from spoke one to hub. So it's coming from spoke one to hub. So you see that name makes sense. It's fully synchronized, they're connected. All the subnets on spoke one can talk to all the subnets on hub one, and all the subnets in hub can talk to spoke one. Now I'm gonna jump to spoke two and do it the other way. So I'm gonna go from spoke two to the hub and we're gonna miss the naming convention. You'll see if that makes sense. So I'm now gonna go from spoke two back to the hub in west three. Gonna create one. And this time I'm gonna use the same name. From spoke two to hub. And I wanna come to hub one. That's the one I wanna work with. Enable both these features. And I'm gonna use the same name to come back because I just, what's the difference? Gonna add this. So you can now see I've got from spoke two to hub. It's fully synchronized, it's connected, it's working great. So I'm gonna go back to the hub. Take a look at its peers. There should be two here now. But look at the name difference. From hub to spoke, which is what that one is. But this one says from spoke two to hub. It still works the right way. It's just named incorrectly. So you're not gonna be able to make it simple when you take a look at just all the peers that you have in a listing. This might be confusing. It might look like you had a redundant one. Now what I'm gonna do is I'm gonna go to the West Europe connection. Done very much the same way. So I'm gonna go from hub. From central EU to hub. And then go out to, and now from central EU to hub. Now while this is coming up, allow gateway or routing services. We talked about that before. And then allow for the gateway to be used by and for routed traffic that you're working with. So there's my three. So I've got from central to hub. I got from spoke two to hub. And I got from hub to spoke. So did I call that correctly? Because I used the same name. But if I go back into central, Europe, and take a look at its name. From central to hub, I use the same name. You can see where that, this one's correct. But the other one was flipped around. So it can get a bit confusing. But there is, and if I went in, all three. So I've got a global VNet peer through central to hub in West US. I've got two spokes in West US also communicating through peers. And currently none of the spokes can communicate directly to each other. They would have to all go through some communications in the hub. So with that, let's go back to the presentation. So hopefully we've seen how easy it is to provide communications between virtual networks. They can be across subscriptions. They can be across regions. Heck, they can even be across tenants. The difference between tenants, you're gonna have to have permissions. And that's why I keep saying it. You have to have permissions at both ends to create the from and permissions to create the two. So to be able to do both of those, you're gonna potentially need permission, especially if it's in a multi-tenanted environment. You might have to have that business to business communication that we talked about in the enter ID feature, where a user in tenant number one has capabilities to maybe create VNets and VNet peering in tenant number two. So all of those all are starting to come together. Hopefully you're seeing a full story. But this is a very simple way to provide a wide area network capability very simply and easily through VNet peering. Thanks for joining us for this session. To continue your learning, watch other videos in the course or explore more on Microsoft Learn at aka.ms.com"

    output = processor.convert(TRANSCRIPT)
    print("Article title:", output.article["title"])
    print("Sections:", len(output.article["sections"]))
    print("Topics:", len(output.notes["topics"]))
