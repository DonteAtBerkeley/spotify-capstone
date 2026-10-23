# Worked label examples (development files only)

Every example here comes from `cost_100.csv`, `checkpoint_500.csv` or `analysis_10000.csv`. **None is a golden-50 review**: the script that picked them checked that the dev sets and `golden_50_to_label.csv` share 0 IDs. These examples are documentation only. They are not sent to the model as few-shot examples, and golden labels are never model inputs.

How to read each entry:
- **Rule label**: the label the shared definitions in `data/GRADING_CONTRACT.md` give. Claude drafted these; Don should review them.
- **Pipeline output**: what `gpt-6-luna` (effort `none`, label_config `gpt-6-luna:effort=none+enrich-p1+s1`) saved in the full run.
- Where the two differ, the entry says so. Those cases show where the model and the rules come apart.

Label fields: topic / intent / severity. Severity scale: 1 none, 2 dislike or generic, 3 degraded with a workaround, 4 core task blocked, 5 explicit serious financial/privacy/data harm.

---

### 1. Premium-only control → `billing`
`8826376c` (analysis_10000)
> Great service for music, but being auto-shuffled on mobile in free version is annoying when it doesn't on free version on gaming consoles...

- **Rule label:** billing / complaint / 3
- **Pipeline output:** billing / complaint / 3, matches.
- Forced shuffle for free users is an *explicitly premium-only control*, which the contract places under billing.
- The opening praise doesn't change the intent: mixed praise and criticism counts as a complaint.
- Severity is 3 because the function is restricted but music still plays.

### 2. The same feature without a paywall → `usability`
`c1f45c02` (analysis_10000)
> Bro loop not showing only hide button shows so i can't loop and shuffle so quickly need this help , spotify lite loop is working pls fix this

- **Rule label:** usability / complaint / 3
- **Pipeline output:** usability / complaint / 3, matches.
- A control is missing from the layout, and nothing ties it to the free tier, so this is usability, not billing.
- Compare example 1: the feature is the same, but the topic depends on whether the text ties it to payment.

### 3. A pure request → severity 1
`41f02d37` (analysis_10000)
> Great app but need to remove shuffle for free and just maybe 2 ads that are unskippable or something

- **Rule label:** billing / request / **1**
- **Pipeline output:** billing / request / **3**. **The severity disagrees.**
- The review asks for a change and reports no failure, so intent is request.
- Severity 1 explicitly covers "a pure feature request."
- The model raised it to 3, probably reacting to the restriction being described. This kind of error raises severity sums in the ranking.

### 4. Login failure → `access`, severity 4
`2784b978` (analysis_10000)
> i have strong internet connection still facing login errors and also i have updated Spotify why I'm facing this issue please solve this it's very irritating

- **Rule label:** access / complaint / 4
- **Pipeline output:** access / complaint / 4, matches.
- Being unable to log in is the contract's own example of a *clearly blocked core task*.

### 5. A threat to leave → `cancellation`, which does not raise severity
`8e19fb8e` (analysis_10000)
> I have changed my CC and now I can't reset my password to enter new card, I am not going to start over, if I can't reset my password then I will just close my account. Help please!

- **Rule label:** access / cancellation / 4
- **Pipeline output:** access / cancellation / 4, matches.
- "I will just close my account" is a threat to leave, and cancellation sits first in the intent precedence.
- The topic is password reset (access), not billing: the card change is only the context.
- Severity is 4 because the password reset is blocked. The cancellation threat adds nothing to severity.

### 6. Crashes that still allow some use → severity 3, not 4
`09ad9589` (analysis_10000)
> Buggy, really buggy. App just crashes randomly all the time. It also doesn't update podcasts when they're available right away, Spotify is just an expensive way to use a cheap app. ...

- **Rule label:** playback / complaint / **3**
- **Pipeline output:** playback / complaint / **4**. **The severity disagrees.**
- Random crashes degrade playback, but the text doesn't say music *cannot* be played, so this is 3.
- "Expensive" is a remark about price, and price alone moves neither topic nor severity.
- Compare `3a7b9052`, "The app just stops playing after one song": playback / complaint / 3 in both columns.

### 7. A specific praised feature → that feature's topic
`1c912ff5` (analysis_10000)
> the app is awesome, it doesn't let me down. love the fact that I can listen to my playlist offline if my phone losses connection in a dead zone.

- **Rule label:** downloads / praise / 1
- **Pipeline output:** downloads / praise / 1, matches.
- In a positive review, the topic is the first *specific* praised feature, here offline listening.
- Compare `880c82e3`, "Love it! Great selection easy to use gui.": catalog / praise / 1. Selection is the first specific thing praised.

### 8. Ad interruptions → `usability`, severity 2
`34019efe` (analysis_10000)
> I like Spotify but there was lot of ads between music .😡😡

- **Rule label:** usability / complaint / 2
- **Pipeline output:** usability / complaint / 2, matches.
- Ad interruptions are listed under usability.
- This is an annoyance with no functional loss, so severity is 2. Angry emoji don't raise it.

### 9. Lyrics behind a paywall → `billing`; lyrics broken → `catalog`
`91f49c48` (analysis_10000)
> I'm Very disappointed by this app now because of the new feature where you will have to buy the premium to access the lyrics ...

- **Rule label:** billing / complaint / 3
- **Pipeline output:** billing / complaint / 3, matches.
- A feature behind a paywall is billing.

`61f32bb4` (analysis_10000)
> Lyrics stopped working with latest update..always something with Spotify that glitches!

- **Rule label:** catalog / complaint / 3
- **Pipeline output:** catalog / complaint / 3, matches.
- Lyrics being unavailable falls under catalog. The two reviews mention the same feature for different reasons.

### 10. Mentioning a paid plan isn't `billing`
`b06b4c1b` (analysis_10000)
> I've been a Spotify premium user for pretty long. I had a suggestion to make, it would be nice if you were able to download the mp3 file of each song as well

- **Rule label:** downloads / request / 1
- **Pipeline output:** downloads / request / 1, matches.
- "Premium user" is context. The request is about downloads.

### 11. Support response → `support`
`d7f0416d` (analysis_10000)
> Your customer service members seriously need retraining on customer service. Half an hour being ignored, each message being read and ignored. ...

- **Rule label:** support / complaint / 2 or 3 (a judgment call)
- **Pipeline output:** support / complaint / 3
- The problem is contacting support and the response.
- The text doesn't say which product function was lost, so 2 is defensible. 3 fits if "being ignored" counts as a degraded support function.
- An ambiguous case like this should be accepted either way, or flagged `needs_review`.

### 12. A bare boycott slogan → `unclear`; a product complaint inside a boycott → `complaint`
`1452ccc8` (analysis_10000)
> This app Sweden I boycott Here the holy book was burnt Boycott Sweden

- **Rule label:** other / unclear / 1
- **Pipeline output:** other / unclear / 1, matches.
- A boycott slogan with no product complaint and no explicit personal departure is unclear.

`d27e9b26` (checkpoint_500)
> Great place for music. Bad for smaller artists and a platform for idiots like Joe Rogan and Steven Crowder to spread their stupidity.

- **Rule label:** other / complaint / 2
- **Pipeline output:** other / complaint / 2, matches.
- This is criticism of the platform mixed with praise, not a slogan.
- No specific product topic is supported, so the topic is other and the severity is generic dislike (2).

### 13. Explicit financial harm → severity 5
`ff7a2f97` (analysis_10000)
> Works perfectly for playing music, but I'm still being charged monthly even though I canceled. ...

- **Rule label:** billing / complaint / 5
- **Pipeline output:** billing / complaint / 5, matches.
- Being charged after cancelling is explicit, serious financial harm.

### 14. Accusations or anger without a stated harm → *not* 5 (pipeline errors)
`3c4ac44e` (analysis_10000)
> Fraud app ever... Never come Cash back offers

- **Rule label:** billing / complaint / **2**, with needs_review = true
- **Pipeline output:** billing / complaint / **5**. **The severity disagrees.**
- The word "fraud" plus an unfulfilled offer is not an *explicit* charge or loss, and the context is missing.

`b1492d81` (analysis_10000)
> I am 😡 angry because spotify owner has destroyed so many qurans astaghfirullah

- **Rule label:** other / **unclear** / **1**
- **Pipeline output:** other / complaint / **5**. **Intent and severity disagree.**
- This is unrelated to the product, with no product complaint and no explicit departure.
- The rules say angry language alone is never severity 5.

These two show why the verification sample, golden evaluation and memo sanity-check matter. Severity-5 outputs from a model with no reasoning effort need spot checks before anyone relies on them.

### 15. Missing context → `needs_review`
`19781735` (analysis_10000)
> It was good but it frustrating me I'm paying and now you know the lyrics I can't copy anymore and yeah I miss a payment that I paid did I get charged again a couple days

- **Rule label:** catalog / complaint / 3, with needs_review = true
- **Pipeline output:** catalog / complaint / 3, needs_review = true, matches.
- The possible double charge is a question, not a supported report, so it doesn't win the "highest supported severity" rule.
- The lyrics restriction is the supported problem. Flagging needs_review instead of guessing an impact follows the contract.

### 16. Non-English text and generic or meaningless text
`eb748acc` (analysis_10000), Indonesian, roughly "Got a horror ad in the middle of the night, uninstalled already, so annoyed"
> Tengah malem dikasih iklan horor, uninstall udah, kesel banget

- **Rule label:** usability / cancellation / 2
- **Pipeline output:** usability / cancellation / 2, matches.
- An explicit uninstall is cancellation. The ad interruption is usability. It's an annoyance only, so severity 2.

`5051c502` (analysis_10000)
> 🤚👎👎👎👎

- **Rule label:** other / complaint / 2
- **Pipeline output:** other / complaint / 2, matches.
- This is general "bad app" sentiment, so complaint with no invented defect.

`b39ba428` (analysis_10000)
> Bicort

- **Rule label:** other / unclear / 1
- **Pipeline output:** other / unclear / 1, matches.
- The text is meaningless.

---

**Tally (23 reviews, including the extra ones cited inline):**
- **Full matches:** 18.
- **Reviews that disagree:** 4 (examples 3, 6, and both reviews in 14). All four have a severity disagreement; `b1492d81` also disagrees on intent.
- **Judgment call:** 1 (example 11).

Every severity disagreement pushes severity *up*, and two of them wrongly reach 5. That bias is the main quality risk for a ranking whose priority score is the sum of severities. The golden-50 evaluation in `evals/` measures it on human labels.
