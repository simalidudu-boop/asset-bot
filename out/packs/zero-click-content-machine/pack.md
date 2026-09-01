# Zero-Click Content Machine

**Automate a week of content in one prompt**

> creators and solo founders who sell digital products · Difficulty: intermediate

A curated pack of prompts that turn one topic into a full content calendar: hooks, posts, and CTAs. Free starter pack.

---

## Prompts

### 1. The Content Matrix

**Use when:** expand one topic into 5 angles

```text
You are a content strategist. Given TOPIC and AUDIENCE, output a 5-cell matrix: hook, bridge, value, proof, CTA. Be specific and non-generic.
```

**Returns:** A table with 5 filled rows, each tailored to the audience.

### 2. Voice Cloner

**Use when:** match your brand voice

```text
Here are 3 samples of my writing: [SAMPLES]. Extract the voice pattern (sentence length, tone, vocabulary) and rewrite: [NEW TEXT] in that voice.
```

**Returns:** Rewritten text + a 3-line voice pattern summary.

### 3. Hook Lab

**Use when:** 10 scroll-stopping openers

```text
Write 10 opening lines for a post about [TOPIC]. Rules: under 12 words, no cliches, each triggers a different emotion. Rank them.
```

**Returns:** 10 ranked hooks with the emotion each one triggers.

---

## Skills

### 1. Auto-title generator

*mine competitor titles for patterns*

1. Paste 3 competitor titles into the prompt.
2. Ask the model to find the pattern (power words, numbers, curiosity gaps).
3. Generate 10 titles for YOUR topic in that pattern.
4. Pick the best with a second model pass.

```python
titles = ['3 titles here']
pattern = llm('what pattern?', titles)
new = llm(f'10 titles in this pattern: {pattern}', topic)
print(new)
```
*Two-pass generation: pattern extraction, then creation.*

### 2. Daily post batcher

*one prompt, seven posts*

1. Give the model your asset link and one topic.
2. Ask for 7 post variants across 4 formats (text, image idea, video script, question).
3. Request a different CTA angle per post.
4. Post one variant per day, staggered.

```python
posts = llm('7 variants for TOPIC, link: LINK', formats=['text','image','video','q'])
for p in posts: post(p)
```
*Batch generation keeps voice consistent across the week.*

---

## Level up

The Pro version adds 30 prompts, 8 video scripts and a fill-in-the-blank content system you can run daily.

👉 [Get the Pro version]({PRO_LINK})

Want a pack built for YOUR niche? Custom prompt packs start at $150.

👉 [Request custom work]({CUSTOM_WORK_LINK})


---

*Generated 2026-09-01 · topic: Prompt engineering for small business owners*