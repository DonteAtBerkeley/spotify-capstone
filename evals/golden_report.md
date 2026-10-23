# Golden-50 evaluation

Records: `grading/records.jsonl.gz`. Human labels: `/Users/donte/spotify-capstone/data/golden_50_labeled.csv`.

**Human-labeled fields: topic, intent, severity only.** Don's golden file leaves sentiment, evidence_quote, entities and needs_review blank, so those fields are *not human-labeled* and are not scored here. Every model `evidence_quote` is still checked in code as an exact substring of its review.

- Golden rows: 50; model completed: 50; missing/quarantined (counted as wrong): 0
- topic agreement: 33/50 = 66.0%
- intent agreement: 41/50 = 82.0%
- severity agreement: 35/50 = 70.0%
- severity MAE (completed only, n=50): 0.34
- severity model − human: {-2: 1, -1: 4, 0: 35, 1: 9, 2: 1}
- all three fields agree: 23/50
- evidence_quote exact-substring check (all completed records): {'ok': 660071}

## Topic confusion

| human \ model | access | usability | playback | downloads | catalog | billing | support | other | MISSING |
|---|---|---|---|---|---|---|---|---|---|
| **access** |  |  |  |  |  |  |  |  |  |
| **usability** |  | 2 | 1 |  | 1 |  |  |  |  |
| **playback** |  | 1 | 2 |  | 1 | 1 |  |  |  |
| **downloads** |  |  |  |  |  |  |  |  |  |
| **catalog** |  |  |  |  |  |  |  |  |  |
| **billing** |  | 1 |  | 1 |  | 3 |  |  |  |
| **support** |  |  | 1 |  |  |  |  |  |  |
| **other** |  | 5 |  |  | 4 |  |  | 26 |  |

## Intent confusion

| human \ model | cancellation | complaint | request | praise | unclear | MISSING |
|---|---|---|---|---|---|---|
| **cancellation** |  |  |  |  |  |  |
| **complaint** | 1 | 16 |  | 1 |  |  |
| **request** | 1 | 3 | 1 |  |  |  |
| **praise** |  |  |  | 18 |  |  |
| **unclear** |  | 1 | 1 | 1 | 6 |  |

## Severity confusion

| human \ model | 1 | 2 | 3 | 4 | 5 | MISSING |
|---|---|---|---|---|---|---|
| **1** | 26 | 4 | 1 |  |  |  |
| **2** |  | 5 | 3 |  |  |  |
| **3** | 1 | 2 | 3 | 2 |  |  |
| **4** |  |  | 1 | 1 |  |  |
| **5** |  |  |  | 1 |  |  |

## Every disagreement (27)

| review_id | fields | human t/i/s | model t/i/s | review text |
|---|---|---|---|---|
| `292ce26a` | topic | other/complaint/2 | catalog/complaint/2 | Staff must be full of mentally ill kool-aid heads. Banning conservative music that speaks truth. Spotify is doing all they can to protect pedophiles, by banning… |
| `991b6b3a` | severity | usability/complaint/3 | usability/complaint/2 | Ads were okay, but limited functionality..it's just too much |
| `0c6ca545` | severity | other/complaint/1 | other/complaint/2 | Hate this application 🤮🤮🤮🤮🤮🤮 |
| `1fc8b08f` | topic|intent | other/unclear/1 | usability/praise/1 | Duo Premium .... No ads at all! |
| `947821dc` | topic|intent|severity | usability/request/4 | playback/complaint/3 | Very good but wen I play my song it o ly plays a little bit then it stops I updated my phone and it worked but it happend again they need to fix this issue |
| `723f07de` | topic|intent|severity | support/request/3 | playback/complaint/4 | Update: I reached out to Spotify Support and with some help from Sarah I was able to get the app working again. Old Post:Normally, the app works great, and I us… |
| `01d453b0` | topic | other/complaint/2 | usability/complaint/2 | I like it but god I hate it when the music Interrupts my ads |
| `ac6cd66d` | topic | other/unclear/1 | catalog/unclear/1 | Lhat ng song nasa spotify |
| `46842184` | topic|intent|severity | other/unclear/1 | catalog/complaint/3 | asem, lirik nya kdang gaada kek mana?? |
| `de48c99b` | topic | usability/praise/1 | catalog/praise/1 | I LOVE that I was able to put in only a few songs I like and Spotify gave me recommendations for an AWESOME Playlist...!!! |
| `372d4e67` | topic|intent|severity | other/unclear/1 | usability/request/2 | Please ye ads ko thoda kumm Karo harr ek song ke baad ad 🙏🙄 |
| `47f1406d` | severity | playback/complaint/3 | playback/complaint/4 | Very poor updates as we cannot playback the songs and most bad updates are happening it is affecting the spotify quality |
| `82780cbe` | intent | other/complaint/1 | other/praise/1 | Awesomeness 👌 👏 👍 😍 💖 |
| `3ddb3f4e` | intent|severity | billing/complaint/2 | billing/cancellation/3 | Deleting this App. The new update suck, we can't choose our fvrt songs after some clicks, we can't CHOOSE song after a song played, and we can't turn off shuffl… |
| `16d640e9` | severity | billing/complaint/2 | billing/complaint/3 | It's my best music app but now it's not...everything basic features is premium.... |
| `8cc4fad4` | severity | other/complaint/1 | other/complaint/2 | I hate this app and sweden .I love islam |
| `215463ae` | intent | playback/request/4 | playback/cancellation/4 | What is happening with Spotify?? Recently I'm trying to play a song but it doesn't working. So I unstalled and thn again install it now I can't even open the ap… |
| `46c0b49f` | topic|severity | playback/complaint/5 | usability/complaint/4 | Are you out of your mind? This is dangerous! Listening to music in a normal volume and suddenly an add starts and my ears feel like they explode!! Stop this BS,… |
| `2aa566c6` | topic | other/praise/1 | usability/praise/1 | Nice app, very less advertising |
| `8c0546b0` | topic|intent | playback/request/3 | catalog/complaint/3 | 1-Lyrics not getting loaded, 2-can't go back to or start song where to wanted. Pathetic update |
| `b58dd6f0` | severity | usability/request/3 | usability/request/1 | The only thing Spotify lacks is the ability to organize saved  albums/artists into collections. Would definitely deserve 5 stars if it  included this feature. |
| `1a41c7e1` | severity | other/complaint/1 | other/complaint/2 | Worst application 👎👎👎 |
| `dceb14e7` | topic | playback/complaint/3 | billing/complaint/3 | I gave one star because I can't give any less than that. the new update is sooooooo annoying like I can't even play the songs that I like and I can't rewind son… |
| `5fba12ea` | topic | other/praise/1 | catalog/praise/1 | I find Spotify very good, it finds and play whatever music you want and also adds songs that you might like, judging from your playlist if you choose to arrange… |
| `ac4e860a` | topic|severity | billing/complaint/2 | downloads/complaint/3 | paying for subscribing but unable to play in offline mode really? |
| `9034d675` | topic|severity | billing/complaint/3 | usability/complaint/2 | Worst app ever too much ad |
| `99b93e31` | topic | other/complaint/2 | usability/complaint/2 | This update very bad for everyone.old Spotify. we all want. |

Full rows: `golden_all.csv`; disagreements only: `golden_disagreements.csv`.
