# Updated Kenya LLM Coding Prompt

You are coding a content analysis dataset for a masculinity / gender norms project.

I will provide a CSV file titled `Final LLM Coding Content Analysis - Kenya.csv`.

The CSV structure is:
- Row 1 contains general directions.
- Row 2 contains the actual column headers/codebook questions.
- Rows 3 onward contain the content snippets to be coded.
- The first columns include `Content ID`, `Context`, and `Content Text / Description`.
- The remaining columns are empty codebook answer columns.

Your task is to fill the empty codebook columns for every content row, starting from row 3.

Return the completed CSV only. Do not add explanations, markdown, notes, or extra columns.

## Evidence Rule

Base coding decisions only on the `Content Text / Description` column.

Use `Context` only to clarify what the content text means. Do not use `Context` as independent evidence.

If something appears only in `Context` but not in `Content Text / Description`, do not code it as present.

Do not use outside knowledge about the influencer, video, tweet, country, or topic.

## Main Goal

Match the human-coded Kenya sample style as closely as possible while keeping the output internally consistent.

The human coder is conservative about whether a concept is present, but once a concept is clearly present, the human coder often selects more than one label in multi-select columns.

Use this balance:
- Do not over-infer.
- Do not force only one label when the text clearly supports two or three labels.
- For short/simple snippets, one label is often enough.
- For richer transcript snippets or multi-idea posts, two or three labels are often appropriate.
- Use three or more labels only when the text clearly supports each one.

## Important Calibration From Human Sample

These patterns are especially important because previous LLM coding under-matched the human coder.

### Q1 Attention-Getter

The human coder is conservative but codes `Yes` for strong openings with:
- startling statistics
- provocative sexual/gender claims
- dramatic claims about harm, threat, or social breakdown
- direct provocative questions
- all-caps or intentionally attention-grabbing language

Do not code ordinary transcript lines as Q1 = `Yes`.

But do code Q1 = `Yes` when the first sentence is clearly meant to shock, provoke, or grab attention.

Examples of human-style Q1 = `Yes`:
- A snippet opening with a statistic like `Over 51,000 women are killed every year...`
- A snippet opening with a provocative gender claim like `The place where women excel is...`
- A snippet opening with a shocking relationship/sexual claim.

When Q1 = `Yes`, Q1a should not be blank.

### Q3 Content Type

Q3 is multi-select.

The human coder often uses two labels when both are visible in the text:
- `Interview/conversational content, Motivational/self-help content`
- `Interview/conversational content, Commentary/reaction content`
- `Motivational/self-help content, Commentary/reaction content`

Use `Interview/conversational content` only when the text itself shows spoken conversation, Q&A, back-and-forth, or a speaker answering/responding.

Use `Motivational/self-help content` when the text advises, encourages, teaches healing, self-care, resilience, responsibility, discipline, or growth.

Use `Commentary/reaction content` when the text critiques, interprets, gives opinion, reacts to gender/society/events, or makes evaluative claims.

For opinion tweets, `Commentary/reaction content` is often the best default.

### Q8 Problems Identified

The human coder often selects `Other` when the problem is clearly present but not well captured by the listed options. Use `Other` more readily than before, but only when there is a clear problem.

Do not combine `No clear problem is identified` with another option.

Use `No clear problem is identified` only if the text does not clearly name or imply a problem.

Human-style examples:
- Male emotional suppression, lack of self-care, or lack of vulnerability can be `Men's behavior` and/or `Mental health/emotional struggle`.
- Femicide, SGBV, institutional failure, or broad violence can be `Global political/social/cultural problems`; add `Other` if the specific problem is not captured well.
- Claims blaming women, wives, girlfriends, feminism, or female behavior are `Women/feminism`.
- Claims criticizing men as irresponsible, abusive, emotionally closed, cheating, or unaccountable are `Men's behavior`.

### Q10 Communication Mode

Use one or two labels for most rows.

Human-style hierarchy:
- Direct instruction or advice: `Advice/instruction`
- Opinion, critique, or interpretation: `Commentary/opinion`
- First-person story/testimony: `Personal story`
- Inspirational or encouraging language: `Motivational speech`
- Factual/statistical/event reporting: `News/telling facts`
- Argument against another position: `Debate/argument`

Common human-style combinations:
- Direct advice plus opinion: `Advice/instruction, Commentary/opinion`
- First-person story with advice: `Advice/instruction, Personal story`
- Opinion based on personal experience: `Commentary/opinion, Personal story`

Do not overuse two labels. Use two labels only when both are central.

### Q11 Audience Needs

Q11 is multi-select and is one of the most important calibration gaps.

The human coder often uses two or three labels. Do not force one label.

Common human-style defaults:
- Advice, explanation, teaching, or interpretation: `Information seeking`
- Gender identity, manhood, fatherhood, womanhood, masculinity, partner roles, or "what kind of person/partner/man/woman to be": `Self expression/identity construction`
- Shared struggle, support, recognition, solidarity, community, men/women seeing themselves in the content: `Connection/social interaction`
- Provocative, dramatic, shocking, mocking, sexualized, or conflict-heavy content: `Entertainment/escapism`
- Wealth, cars, success, superiority, high-value identity, respect, or status: `Status seeking`
- Announcing, recording, reporting, or documenting public events/campaigns/incidents: `Documentation of events`

Human-style patterns:
- Advice about men, fathers, husbands, women, relationships, or gender roles usually gets:
  `Information seeking, Self expression/identity construction`
- Advice that also invites shared struggle/support usually gets:
  `Connection/social interaction, Self expression/identity construction, Information seeking`
- Provocative gender commentary often gets:
  `Entertainment/escapism, Self expression/identity construction`
- Provocative gender commentary about status/superiority often gets:
  `Entertainment/escapism, Self expression/identity construction, Status seeking`

Use `None of these apply` only when no audience need is clear. Do not combine it with other labels.

### Q12 Support for Claims

Q12 is multi-select.

Human coder uses multiple labels when multiple support types are visible.

Do not default to `No support` if the text contains any clear support type.

Use:
- `Generalizations about men/women` for broad claims about men, women, husbands, wives, fathers, mothers, feminism, modern women, etc.
- `Personal experience` for first-person life experience.
- `Stories about men/women` for examples/narratives about other people.
- `Cultural/social observations` for claims about society, culture, institutions, norms, trends, or public behavior.
- `Facts/statistics` for numbers, data, percentages, or measurable factual claims.
- `Moral/religious claims` for God, faith, sin, morality, tradition, right/wrong.
- `No support` only when the text simply asserts without evidence, examples, observations, data, or moral/religious framing.

Do not combine `No support` with other labels.

### Q13 Claim Justification

Q13 is multi-select.

Human-style default:
- If a claim is asserted as obvious truth, reality, "how things are," or self-evident, use `Presented as common sense`.
- If it gives a personal/observed example, use `Anecdotal examples`.
- If it gives statistics or numbers, use `References data`.
- If it invokes God, faith, tradition, culture, morality, or religion, use `References religion/tradition`.
- If it cites news, public figures, other influencers, or named outside sources, use `References external sources such as other influencers`.
- Use `No justification` only when the text gives no apparent reason, example, evidence, or self-evident framing.

Do not combine `No justification` with other labels.

### Sentiment Questions Q14, Q15, Q16

These were major disagreement points. Use the following thresholds.

Q14 sentiment toward men:
- `Positive`: men are praised, defended, encouraged, valued, centered sympathetically, or framed as needing support.
- `Negative`: men are blamed, criticized, mocked, described as weak/harmful/irresponsible/abusive.
- `Mixed`: both positive and negative evaluation of men appear.
- `Neutral`: men are mentioned without clear evaluation.
- `Unclear`: men are present but sentiment is hard to determine.
- `Not mentioned`: men are not directly or clearly referenced.

Q15 sentiment toward women:
- `Positive`: women are protected, respected, empathized with, defended, or supported.
- `Negative`: women are blamed, mocked, distrusted, degraded, portrayed as inferior/manipulative/immoral/dangerous.
- `Mixed`: both positive and negative evaluation of women appear.
- `Neutral`: women are mentioned without clear evaluation.
- `Unclear`: women are present but sentiment is hard to determine.
- `Not mentioned`: women are not directly or clearly referenced.

Q16 sentiment toward traditional gender norms:
- `Positive`: supports male leadership, female submission, male provision, rigid gender roles, sexual double standards, hierarchy, stoicism, men being naturally superior, or women as naturally suited to domestic/mother roles.
- `Negative`: critiques traditional norms, toxic masculinity, patriarchy, emotional suppression, inequality, harmful gender expectations, or rigid roles.
- `Mixed`: both supports and critiques traditional norms.
- `Neutral`: traditional norms are referenced without clear evaluation.
- `Unclear`: traditional norms are implicated but sentiment is hard to determine.
- `Not mentioned`: no traditional gender norm is clearly referenced.

Important human-style pattern:
- Regressive/traditional content that praises male dominance, male superiority, female domesticity/submission, or male provision should usually be Q16 = `Positive`.
- Progressive content critiquing emotional suppression, toxic masculinity, violence, or rigid roles should usually be Q16 = `Negative`.

### Q18 and Q18a Calls to Action

Be conservative about Q18, but not too conservative.

Code Q18 = `Yes` when the text clearly tells, urges, recommends, commands, or encourages an audience/group to do something.

Direct self-care, healing, behavior-change, relationship, voting, support, or social action language counts as a call to action if phrased as instruction/recommendation.

If Q18 = `Yes`, Q18a must be filled.

Human coder uses `Other` in Q18a when the call to action is real but not covered by listed options, such as:
- build community
- seek support
- take care of yourself
- change behavior generally
- attend/report/support a campaign

## Formatting Rules

1. Preserve row 1 exactly.
2. Preserve row 2 exactly.
3. Preserve row order exactly.
4. Do not change `Content ID`, `Context`, or `Content Text / Description`.
5. Do not change column names.
6. Code only rows 3 onward.
7. Every non-empty content row must be coded.
8. Blank rows, if any, should remain blank.
9. Use comma-separated values for multi-select columns.
10. Do not use semicolons.
11. Do not add explanations or notes.
12. Return only the completed CSV.

## Multi-Select Columns

These columns are multi-select:
- Q1a attention-getting strategies
- Q2 primary topics
- Q3 content type
- Q7 what men need to do
- Q8 problem identified
- Q9 solution proposed
- Q10 communication mode
- Q11 audience needs
- Q12 support for claims
- Q13 claim justification
- Q18a call-to-action type

For Q2, Q3, Q7, Q8, Q9, Q10, Q11, Q12, and Q13:
- Use 1 label if only one category is clearly central.
- Use 2 labels when two categories are clearly present.
- Use 3 labels when the snippet clearly combines three distinct ideas.
- Do not force only one label.
- Do not add labels that are only weakly implied.

## Open-Text Other Specify Rules

These are open-text specify fields:
- Q1b
- Q2a
- Q3a
- Q7a
- Q8a
- Q9a
- Q10a
- Q12a
- Q13a
- Q18b

Rules:
1. If the previous answer includes `Other`, the matching specify field must be filled with a short 1-5 word phrase.
2. If the previous answer does not include `Other`, the matching specify field must be blank.
3. Do not write `N/A`, `Not applicable`, `None`, `No`, `Blank`, or `-` in open-text specify fields.
4. Avoid selecting `Other` when an existing option is close enough.
5. Do not select `Other` just to add explanation.

## Conditional Coding Rules

Keep conditional fields internally consistent even if the human sample contains occasional inconsistencies.

For Q5:
- If Q4 = `No`, Q5 must be `Does not address masculinity or gender norms`.

For Q6:
- If Q4 = `No`, Q6 must be `Not applicable`.
- If Q4 = `Yes, explicitly` or `Yes, implicitly`, choose `Yes`, `No`, or `Unclear`.
- Choose `Yes` only if the text clearly says or strongly implies what men should do, be, feel, avoid, become, believe, provide, lead, control, heal, or change.
- Choose `No` if gender/masculinity is present but no clear instruction or expectation for men appears.
- Choose `Unclear` if ambiguous.

For Q7:
- If Q6 = `No` or Q6 = `Not applicable`, Q7 must be `Not applicable`.
- If Q6 = `Unclear`, Q7 must be `Mixed/unclear`.
- If Q6 = `Yes`, select only clearly present options.

For Q18a:
- If Q18 = `No`, Q18a and Q18b must be blank.
- If Q18 = `Yes`, Q18a must contain at least one applicable call-to-action type.
- If Q18a includes `Other`, Q18b must be filled.
- If Q18a does not include `Other`, Q18b must be blank.

## Human-Style Answer Labels

Use exactly these labels in output.

### Q1. Does the content start with an attention-getter?

Options:
- Yes
- No

### Q1a. If yes, what kind of attention-getting strategies does it use?

Options:
- Compelling question
- Use of all CAPS
- Humor or sarcasm
- Shares something violent or gross
- Shares something sexual
- Shares something surprising
- Uses a news headline or social media trend as opener
- Interesting visual or meme
- Other

If Q1 = `No`, leave Q1a and Q1b blank.

### Q2. What is/are the primary topic(s) of the content?

Options:
- Dating/marriage
- Friends/socializing
- Family/children
- Money/status
- Fitness/self-improvement
- Mental health
- Gender issues
- Social issues
- Religion/morality
- Gaming/technology
- Other

Use `Gender issues`, not `Gender issues, e.g. equality`.

Use `Social issues`, not `Social issues, e.g. corruption`.

Select all clearly central topics, not every minor reference.

Human-style patterns:
- Relationships involving men/women: usually `Dating/marriage, Gender issues`.
- Fathers/children plus gender roles: usually `Family/children, Gender issues`.
- Men, provision, money, cars, success, status: usually `Money/status, Gender issues`.
- Male trauma, vulnerability, healing, emotional openness: usually `Mental health, Gender issues`.
- Violence, rape, abuse, social harm, institutions: usually `Social issues`, and add `Gender issues` when gender is central.

### Q3. Characterize the type of content.

Options:
- Interview/conversational content
- Motivational/self-help content
- Commentary/reaction content
- Other

Q3 is multi-select.

### Q4. Does this content address masculinity / gender norms?

Options:
- Yes, explicitly
- Yes, implicitly
- No

`Yes, explicitly` means the content text directly mentions men, women, masculinity, manhood, gender roles, husbands, wives, fathers, mothers, feminism, equality, submission, provision, male/female expectations, or similar gendered terms.

`Yes, implicitly` means gender/masculinity is clearly present but not directly named.

`No` means no meaningful gender/masculinity connection in the content text.

### Q5. If yes, how would you characterize the type of masculinity or gender norms addressed?

Options:
- More regressive/traditional/restrictive
- More progressive/equitable/expansive
- Mixed/unclear
- Does not address masculinity or gender norms

### Q6. If yes, does the content address what men should do or be in society?

Options:
- Yes
- No
- Unclear
- Not applicable

### Q7. If yes, what does the content indicate men do or need to do?

Options:
- Men need to dominate/lead
- Men need to provide/succeed
- Men are disadvantaged/victims
- Men need to improve themselves
- Men need to be fully self-reliant
- Men need to be emotionally open
- Men need to not show emotions
- Men need to be equal partners
- Mixed/unclear
- Other
- Not applicable

### Q8. What problem is being identified in the content?

Options:
- Kenyan or Nigerian political/social problems
- Global political/social/cultural problems
- Western political/social influence
- Women/feminism
- Men's behavior
- Economic/status pressure
- Mental health/emotional struggle
- No clear problem is identified
- Other

Do not combine `No clear problem is identified` with other options.

### Q9. What solution is being proposed?

Options:
- Social or political change
- Assert dominance/control
- More wealth/status
- More self-discipline/fitness
- More emotional growth/healing
- More equality/respect for men
- More equality/respect for women
- Building community
- No clear solution
- Other

Do not combine `No clear solution` with other options.

### Q10. How would you characterize the communication mode of this content?

Options:
- Advice/instruction
- Personal story
- Commentary/opinion
- Debate/argument
- Humor/satire
- Motivational speech
- News/telling facts
- Other

### Q11. Which audience needs does the content aim to fulfill?

Options:
- Entertainment/escapism
- Information seeking
- Connection/social interaction
- Self expression/identity construction
- Status seeking
- Documentation of events
- None of these apply

Do not combine `None of these apply` with other options.

### Q12. How does the content support its claims or messages?

Options:
- Generalizations about men/women
- Personal experience
- Stories about men/women
- Cultural/social observations
- Facts/statistics
- Moral/religious claims
- Mixed
- No support
- Other

Do not combine `No support` with other options.

### Q13. How are the claims justified?

Options:
- No justification
- Anecdotal examples
- Presented as common sense
- References data
- References religion/tradition
- References external sources such as other influencers
- Other

Do not combine `No justification` with other options.

Use `References external sources such as other influencers` without an internal comma.

### Q14. What is the general sentiment toward men?

Options:
- Negative
- Positive
- Mixed
- Neutral
- Unclear
- Not mentioned

### Q15. What is the general sentiment toward women?

Options:
- Negative
- Positive
- Mixed
- Neutral
- Unclear
- Not mentioned

### Q16. What is the general sentiment toward traditional gender norms?

Options:
- Negative
- Positive
- Mixed
- Neutral
- Unclear
- Not mentioned

### Q17. Does the content use fear or threat to help drive the message home?

Options:
- Yes
- Somewhat
- No

Code `Yes` only when fear/threat is clearly used as a persuasive device.

Code `Somewhat` for mild warning, implied risk, or caution.

### Q18. Does the content include any calls to action to the audience?

Options:
- Yes
- No

### Q18a. If yes, what kinds of calls to action are included?

Options:
- Calls for audience to like the content
- Calls for audience to share the content
- Calls for audience to follow the speaker on social media
- Calls for men to follow more traditional gender norms
- Calls for men to follow more equitable gender norms
- Calls for women to follow more traditional gender norms
- Calls for women to follow more equitable gender norms
- Calls for politicians or social figures to do something
- Calls for audience to vote in a different way
- Other

## Final Output Check

Before returning the completed CSV, verify:
1. Row 1 is unchanged.
2. Row 2 is unchanged.
3. Row order is unchanged.
4. `Content ID`, `Context`, and `Content Text / Description` are unchanged.
5. Every non-empty row is coded.
6. Multi-select answers use commas, not semicolons.
7. Q2 uses `Gender issues` and `Social issues`.
8. Q3, Q12, and Q13 can contain multiple comma-separated labels.
9. `Other` answers have matching specify fields.
10. Non-`Other` answers have blank specify fields.
11. Q5, Q6, Q7, Q18a, and Q18b follow conditional rules.
12. The output is only the completed CSV.
