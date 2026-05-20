---
name: review_interface
description: 'Convert long AI-generated plans, specs, research, or proposals into an ADHD-friendly self-contained HTML review workspace.'
---

## Parameters

- **source_content**:
  Raw AI-generated content to transform into a review interface. This can be pasted text, current conversation output, or a referenced local file.
  Required.
- **title**: Optional document title. If blank, infer a concise title from the source without inventing facts. Default: "".
- **audience**: Primary reader: founder, engineer, PM, designer, exec, or general. Default: "busy technical reviewer".
- **density**: Preferred density: concise, balanced, or detailed. Default: "balanced".
- **output_path**: Optional path for the generated self-contained HTML file. If blank, return the HTML directly. Default: "".

## Context

- **review-workspace-goal**

  This skill turns dense AI-generated plans, specs, research notes, proposals, PRDs, implementation plans, architecture docs, and brainstorms into review interfaces that speed up human comprehension and decision-making.

- **reader-model**

  Assume the reader may be distractible, time-limited, or overwhelmed by long prose. The default experience should be skimmable, chunked, labeled, and progressively disclosed.

- **source-audit-model**

  The transformed interface should preserve a collapsed raw source view so readers can inspect original wording when they need to verify a summary, decision, risk, or ambiguity.

## Constraints

- **Must:** Preserve the important meaning, decisions, risks, action items, assumptions, constraints, open questions, and technical details from the source.
- **Must:** Output exactly one complete self-contained HTML document with inline CSS and inline JavaScript only.
- **Must:** Mark each uncertain or inferred item explicitly as confirmed, inferred, unclear, or contradictory.
- **Require:** Keep the default view concise and put dense details behind accordions, tabs, or show-more sections.
- **Require:** Make the document feel like a review workspace with summaries, status badges, dashboards, tables, checklists, and clear navigation.
- **Avoid:** Adding facts, owners, dates, metrics, recommendations, or decisions that are not supported by the source.
- **Avoid:** Presenting long continuous prose or unlabeled sections that force the reader to parse everything sequentially.
- **Avoid:** Depending on external scripts, stylesheets, fonts, CDNs, Mermaid libraries, image URLs, or network access for the HTML to work.
- **Avoid:** Using generic AI-looking gradients, oversized hero sections, decorative blobs, flashy animation, or marketing-style layout that distracts from review.

## Steps

1. Follow the collect-inputs procedure below.
2. Follow the extract-review-units procedure below.
3. Follow the normalize-for-review procedure below.
4. Follow the choose-interface-shape procedure below.
5. Follow the render-html procedure below.
6. Follow the verify-interface procedure below.
7. Follow the deliver-interface procedure below.

### Procedure: collect-inputs

1. Decide whether the source content is missing, empty, inaccessible, or only described indirectly applies and, if so:
   a. Ask the user for the raw content or the local file path to transform.
2. Decide whether density is not one of concise, balanced, or detailed applies and, if so:
   a. Default density to balanced and continue.
3. Decide whether audience is missing or vague applies and, if so:
   a. Default audience to busy technical reviewer and continue.
4. Decide whether title is missing or blank applies and, if so:
   a. Infer a short factual title from the source. If no safe title can be inferred, use `Review Document`.
5. Decide which of the following applies and follow only that path:
   If output_path is provided:
   a. Plan to write the final HTML file to {output_path}.
   Otherwise:
   a. Plan to return the HTML directly.

### Procedure: extract-review-units

1. Read the source content closely and identify the document type: technical spec, product plan, implementation plan, research, proposal, brainstorm, review, or other.
2. Extract only supported information from the source: TL;DR, goals, non-goals, decisions, action items, risks, open questions, assumptions, constraints, dependencies, milestones, owners, stakeholders, architecture, APIs, services, metrics, success criteria, contradictions, and unresolved ambiguities.
3. For every extracted item, decide whether it is confirmed by the source, inferred from surrounding context, or unclear.
4. Preserve important technical details, names, dates, owners, dependencies, and decision language exactly enough that the transformed document stays faithful.
5. Carry the structured review units forward for the remaining procedures.

### Procedure: normalize-for-review

1. De-duplicate repeated ideas and merge scattered TODOs into one action section.
2. Convert long prose into short bullets, tables, cards, timelines, checklists, and collapsible detail panels.
3. Convert comparisons into tables, procedures into numbered steps, scattered risks into risk cards, and scattered unknowns into one open-questions area.
4. Cluster brainstorm content into themes and identify the most supported direction only when the source supports one.
5. Flag contradictions clearly instead of smoothing them over.
6. Omit categories that are absent from the source. Do not fabricate missing owners, dates, metrics, or recommendations.
7. Carry the deduplicated review-ready units forward for interface selection and rendering.

### Procedure: choose-interface-shape

1. Choose the smallest interface structure that lets the reader understand the document quickly.
2. Use a dashboard-style overview when the source is long, decision-heavy, risk-heavy, or contains many action items.
3. Include sections only when applicable: top review bar, TL;DR, review dashboard, key decisions, action plan, risks and open questions, architecture or flow, details on demand, contradictions, and source view.
4. Tune density for {density}: concise keeps defaults very short, balanced includes essential context, detailed exposes more accordions without turning the default view into long prose.
5. Tune labels and section ordering for {audience}, while preserving the same facts and uncertainty labels.
6. Carry the selected information architecture forward into HTML rendering.

### Procedure: render-html

1. Produce one complete self-contained HTML document using semantic HTML, inline CSS, and inline JavaScript only.
2. Render the top area with title, document type, audience, density, counts for decisions, actions, risks, and open questions, a light/dark toggle, expand all and collapse all controls, and a reading-progress indicator.
3. Put a TL;DR near the top with 5 to 8 short bullets covering what this is, why it matters, what is proposed or changed, what decisions are needed, and what happens next.
4. Render key decisions as compact cards or a responsive table with decision, status, owner when present, impact, confidence, and deadline when present. Make unresolved decisions obvious.
5. Render the action plan as Now, Next, Later or source-provided phases. Preserve dependencies, blockers, owners, dates, and verification steps when present.
6. Render risks and open questions as collapsible cards labeled by severity and confidence. Include mitigations or next steps when present.
7. Render architecture, flows, components, APIs, services, and system structure only when the source contains them. Prefer component cards, sequence steps, dependency lists, and simple inline SVG or CSS diagrams when they improve comprehension.
8. Put dense notes, edge cases, alternatives, implementation details, and lower-priority context behind accordions, tabs, or show-more regions.
9. Include the original source in a collapsed source-view panel so the reader can audit the transformation.
10. Keep the visual design neutral, high contrast, uncluttered, and optimized for reading instead of marketing.
11. Avoid external scripts, external stylesheets, external fonts, CDNs, generated gradients, decorative blobs, and flashy effects.
12. Carry the complete self-contained HTML document forward for verification and delivery.

### Procedure: verify-interface

1. Check the HTML for the main failure modes: walls of text, missing raw source view, invented facts, unmarked uncertainty, inaccessible controls, weak contrast, broken keyboard interaction, mobile overflow, and print-hostile layout.
2. Ensure paragraphs are short, important items appear before details, unresolved decisions and high risks are easy to find, and every collapsible control has clear text.
3. Ensure the document remains readable if JavaScript fails, respects reduced-motion preferences, and includes print-friendly CSS.
4. Revise the HTML before delivery if any check fails.

### Procedure: deliver-interface

1. Decide which of the following applies and follow only that path:
   If output_path is provided:
   a. Write the HTML document to {output_path}. Report the saved path and a concise summary of what was generated.
   Otherwise:
   a. Return only the final HTML document. Do not wrap it in Markdown fences and do not add explanatory commentary before or after it.

