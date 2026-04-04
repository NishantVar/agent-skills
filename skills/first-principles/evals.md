# First Principles Skill — Evaluation Test Cases

Multi-turn conversation scenarios for testing the first-principles skill. Each test case has a user script (simulating turns) and specific evaluation criteria.

---

## Test Case 1: Tech Decision — "We need to rewrite in Rust"

**Tests:** Assumption surfacing, research grounding, not being adversarial

**User turns:**

1. `"Break this down from first principles: our team is saying we need to rewrite our Python backend in Rust for performance."`
2. `"Well, our API response times are around 800ms and users are complaining. The team says Python is just slow."`
3. `"I think so? We haven't really profiled it. But everyone knows Python is slower than Rust."`
4. `"Hmm, okay that's a good point. What should we actually look at before deciding?"`

**Evaluate:**

- Does it restate the problem before diving in? (Step 1)
- Does it surface the hidden assumption ("Python is the bottleneck") without being combative?
- Does it research Python vs Rust performance *in context* (web APIs, I/O-bound vs CPU-bound)?
- Does it catch "everyone knows" as conventional wisdom and push on it?
- Does it stay collaborative when the user admits they haven't profiled?
- Does it avoid jumping to "just use Rust" or "don't use Rust" — staying in decomposition mode?

---

## Test Case 2: Business Model — "Freemium is the only way"

**Tests:** Iterative why decomposition depth, hitting actual bedrock, anti-"it depends"

**User turns:**

1. `"First principles this for me: we're building a SaaS tool and I'm convinced freemium is the right model."`
2. `"Because that's how all successful SaaS companies do it — Slack, Dropbox, Notion all started freemium."`
3. `"Users need to experience the product before they pay. You can't sell something people haven't tried."`
4. `"I guess the fundamental truth is that people don't pay for things they haven't experienced."`
5. `"Okay, what are the actual fundamentals here then?"`

**Evaluate:**

- Does it decompose past "that's how successful companies do it" (survivorship bias)?
- Does it challenge "you can't sell something people haven't tried" — is that actually true? (enterprise sales, consulting, etc.)
- Does it research whether freemium actually works for most SaaS (conversion rates, CAC)?
- Does it catch the user's proposed "fundamental" in turn 4 and test it further rather than accepting it?
- When laying out fundamentals (Step 4), are they genuinely irreducible, not just rephrased assumptions?
- Does it avoid vague "it depends on your market" — and instead get specific?

---

## Test Case 3: Personal Decision — "Should I get an MBA?"

**Tests:** Tone/empathy, knowing when to stop, rebuild step, user-input moments

**User turns:**

1. `"Help me think about this from first principles — should I get an MBA? I'm 28, working as a product manager."`
2. `"I want to move into a VP role eventually, and everyone at that level at my company has an MBA."`
3. `"I think an MBA teaches you how to think strategically and gives you credibility."`
4. `"Actually, you're right that credibility might just be signaling. But the network is real — you meet people who help your career later."`
5. `"Okay, I think I see the fundamentals now. Can you help me think about what to actually do?"`

**Evaluate:**

- Does it handle a personal/emotional topic with appropriate warmth?
- Does it decompose "everyone at VP level has an MBA" — is it causal or correlational?
- Does it research MBA ROI data rather than just reasoning about it?
- Does it distinguish between what an MBA *actually provides* vs what people *believe* it provides?
- When the user agrees on "signaling" but pushes back on "network" — does it take that seriously and explore it rather than dismissing?
- Does it transition to Step 5 (Rebuild) when the user asks in turn 5, with concrete structure?

---

## Test Case 4: False Claim — "Humans only use 10% of their brain"

**Tests:** Research to correct misinformation, not being preachy, handling user pushback

**User turns:**

1. `"I want to get to the root of this: we only use 10% of our brain, so there must be massive untapped potential for cognitive enhancement."`
2. `"I've read it in multiple books and heard neuroscientists mention it in talks."`
3. `"Okay fine, maybe not literally 10%, but we clearly don't use our full cognitive capacity all the time, right?"`
4. `"So what IS actually true about cognitive enhancement?"`

**Evaluate:**

- Does it research the 10% myth immediately rather than arguing from logic alone?
- Does it correct the claim without being preachy or making the user feel dumb?
- When the user retreats to a softer claim in turn 3 ("we don't use full capacity") — does it treat this as a new claim to examine, not just a concession to accept?
- Does it ground the cognitive enhancement discussion in actual neuroscience research?
- Does it distinguish between the myth and the legitimate questions underneath it?

---

## Test Case 5: Abstract/Philosophical — "Is remote work better?"

**Tests:** Handling ambiguity, assumption prioritization, going deep without going too deep

**User turns:**

1. `"Rethink from scratch: is remote work actually better than in-office?"`
2. `"Better for productivity. I feel like I get more done at home."`
3. `"I don't have data, but I have fewer meetings and fewer interruptions."`
4. `"Hmm, that's true — I also miss some of the spontaneous conversations. But those feel inefficient in the moment."`
5. `"I think I have what I need. Let me just see the fundamentals."`

**Evaluate:**

- Does it immediately ask "better for whom? better how?" to narrow the ambiguity?
- Does it separate "I feel more productive" from "I am more productive"?
- Does it research remote work productivity studies rather than just debating anecdotes?
- Does it handle the user's contradictory feelings (fewer interruptions good, missing spontaneity bad) without forcing a conclusion?
- When user says "I have what I need" in turn 5 — does it respect that and deliver Step 4 cleanly without pushing to Step 5?
- Does it avoid going philosophical ("what is productivity, really?") when the user wants practical answers?

---

## Test Case 6: Technical Architecture — "We should use microservices"

**Tests:** Full flow end-to-end including rebuild, steel-manning assumptions before discarding

**User turns:**

1. `"What's fundamental here — should our 4-person startup use microservices for our new product?"`
2. `"Because we want to scale. If we build a monolith now, we'll just have to rewrite later."`
3. `"Netflix and Uber use microservices, and they handle massive scale."`
4. `"Okay, I see. So the fundamental question is really about our current constraints vs future needs?"`
5. `"Actually yes, walk me through what we'd build if we only followed the fundamentals."`
6. `"That makes sense. What about when we actually DO need to scale — how would we know?"`

**Evaluate:**

- Does it steel-man the microservices argument before challenging it? (There ARE legitimate reasons)
- Does it research team-size-to-architecture studies and Netflix/Uber's actual evolution (they started as monoliths)?
- Does it identify the core tension: optimizing for today vs. optimizing for a future that may not come?
- Does it handle 6 turns of conversation coherently without losing the thread?
- In the rebuild phase (turns 5-6), does it give concrete, actionable guidance rather than generic advice?
- Does it answer the "how would we know when to switch" question with specific signals, not hand-wavy "when you need to"?

---

## Test Case 7: Mathematical — "Why does compound interest grow so fast?"

**Tests:** Reaching actual mathematical bedrock, knowing when you've hit a law, research for historical/empirical grounding

**User turns:**

1. `"Break this down from first principles: why does compound interest make such a massive difference over time? Like why does investing early matter SO much?"`
2. `"I get that you earn interest on interest, but why does that create such a dramatic curve? A few percent shouldn't matter that much."`
3. `"Okay, so it's exponential growth. But why does exponential growth feel so unintuitive? Like why do people consistently underestimate it?"`
4. `"So is the fundamental truth here just about math, or is there something deeper about why this particular math matters for financial decisions?"`
5. `"What about the rule of 72? Is that actually accurate or just a rough trick?"`

**Evaluate:**

- Does it ground the explanation in actual math — the formula A = P(1 + r/n)^(nt) — and show why the exponent drives everything?
- Does it recognize that exponential growth is genuine mathematical bedrock (a property of repeated multiplication) and stop decomposing there rather than going further?
- When the user asks about intuition in turn 3, does it research cognitive biases (exponential growth bias / linearization bias) rather than just guessing?
- Does it connect the math to real numbers — e.g., research actual historical market returns to show the difference between starting at 25 vs 35?
- For the Rule of 72 (turn 5), does it derive it mathematically (ln(2)/r ~ 72/r%) and explain when it breaks down (high rates)?
- Does it distinguish between mathematical fundamentals (exponential growth, the formula) and empirical fundamentals (historical market returns, human cognitive biases) — these are different types of bedrock?
