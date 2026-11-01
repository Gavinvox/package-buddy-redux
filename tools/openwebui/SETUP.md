# Package Tracker (17TRACK) tool for Mira — setup

This adds a tool (version 1.1.0) to Open WebUI so Mira (gemma4:31b) can check packages through your 17TRACK account.
You need: admin access to Open WebUI, and your 17TRACK API key.

## 1. Add the tool
(Updating from an older version? Open the tool under **Workspace > Tools**, replace all the code with the new file, and click **Save**. Your API key stays.)
1. Open Open WebUI in your browser and sign in as admin.
2. Click **Workspace** (left sidebar), then the **Tools** tab.
3. Click the **+** button (top right) to create a new tool.
4. Delete the sample code in the editor. Open `openwebui_17track_tool.py`, copy everything, and paste it in.
   The Name, ID and Description fill in by themselves from the top of the file.
5. Click **Save** at the bottom.

## 2. Put in your 17TRACK key
1. Back on **Workspace > Tools**, find **Package Tracker (17TRACK)**.
2. Click its **gear icon** (Valves).
3. Paste your key into **API_KEY** and click **Save**.
   Leave the other settings alone. Turn **AUTO_REGISTER** off if you want Mira to never spend quota on her own.

## 3. Give the tool to Mira
Do one of these:
- **Always on (recommended):** **Workspace > Models** > click the pencil next to the model Mira uses > in **Tools**, tick **Package Tracker (17TRACK)** > **Save & Update**.
- **Just one chat:** in the chat box, click the **Integrations** icon (four little diamonds next to **+**) > **Tools** > switch on **Package Tracker (17TRACK)**.

## 4. Settings for gemma4:31b (important)
gemma4 supports tool calling in Ollama (its library page carries the **tools** tag).
In the same model editor, open **Advanced Params**:
- **Function Calling: Native.** In Open WebUI 0.10 and later this is already the default; on older versions pick Native by hand.
- **Context Length (Ollama) / num_ctx: 32768** (16384 at minimum). Open WebUI's low default overrides Ollama's own setting, and
  gemma4 then gives blank replies or never calls tools. This is the most common reason it fails.
Save. Also keep Ollama up to date (`docker pull ollama/ollama` in Portainer, then recreate the container); newer Ollama repairs
gemma4's occasional malformed tool calls.

## Carrier names Mira understands
You can usually leave the carrier out and 17TRACK will guess. If it guesses wrong, name it, e.g. "track ... with canada post".

| Say | 17TRACK code |
|---|---|
| usps | 21051 |
| ups | 100002 |
| fedex | 100003 |
| dhl / dhl express | 100001 |
| dhl ecommerce | 7047 |
| royal mail | 11031 |
| amazon / amazon logistics | 100308 |
| amazon shipping us | 101392 |
| canada post / canadapost | 3041 |
| china post | 3011 |
| china ems (separate from China Post in 17TRACK) | 3013 |
| yunexpress / yun express | 190008 |
| 4px | 190094 |
| yanwen | 190012 |
| sf express / sf (international) | 100012 |
| sf express cn (China domestic) | 190766 |
| japan post / japan ems (one code covers both) | 10021 |
| korea post / kpost / korea ems / k-packet (one code) | 11051 |
| korea post domestic | 11054 |
| chunghwa post / taiwan post | 20011 |
| chunghwa post domestic | 20012 |

## 5. Try it
- "How many 17TRACK credits do I have left?"
- "List the packages I'm tracking."
- "Where is TBA000000000001?"
- "Check TBA000000000002 again, don't register anything."
- "Track <a real UPS/FedEx/DHL number> with UPS." (new number: uses 1 credit)
- "Track <a real China Post number> with china post." (new number: uses 1 credit)
- "TBA000000000001 is under the wrong carrier, change it to amazon shipping us."
Below the question you should see a little status line such as "Checking … with 17TRACK…". That means the tool ran.

## Troubleshooting
- **Mira answers without using the tool / makes up tracking info:** make sure the tool is ticked for the model or the chat,
  Function Calling is Native, and num_ctx is raised. Say "use the package tracker tool" in the question.
- **Blank reply or endless spinner with gemma4:** raise num_ctx (step 4) and update Ollama.
- **Raw text like `<|tool_call>call:...` appears in the chat:** update Ollama and Open WebUI, and make sure Function Calling is Native.
- **"Could not reach api.17track.net":** the Open WebUI container has no internet. Test it from the server terminal (copy just this line):
  `docker exec open-webui python3 -c "import urllib.request;print(urllib.request.urlopen('https://api.17track.net/en').status)"`
  It should print 200. (Change `open-webui` if your container has a different name in Portainer.)
- **"HTTP 401 ... Access token is invalid":** the key in the gear menu is wrong or has a space in it.
- **"No 17TRACK API key is set":** step 2 wasn't saved.
- **17TRACK errors are shown word for word**, for example:
  - `-18019823 ... policy restrictions of the carrier 'USPS' ... registration is temporarily not supported` = USPS is blocked on the free plan (no credit used).
  - `-18019902 ... does not register, please register first` = that number isn't on your account yet.
  - Status `NotFound / NotFound_Other` with no events = 17TRACK asked the carrier and got nothing (normal so far for Amazon TBA numbers).
- **Changed the code later and Save fails with "Current Valves are incompatible":** reset the gear settings, then save again.

Safety note: tools run Python on your server, so only admins should have Workspace access.
