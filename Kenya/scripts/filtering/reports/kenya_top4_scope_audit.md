# Kenya Top-4 Scope Audit

Scope reference: content should explicitly or implicitly engage masculinity-focused discourse, regressive gender norms, misogyny/manosphere-adjacent narratives, or closely related audience reception.

Audited files were the four Kenya pieces with the largest comment volumes:

1. `Tiktok; Young man who thinks it's a shame not having a car at 35.xlsx` (1,918 source comments)
2. `Tiktok; Men Are Not Missing. They Are Evolving!.csv.xlsx` (1,493 source comments)
3. `Full Tweet Stay away from vulgar women.xlsx` (858 source comments)
4. `Tweet_A woman can't love a man. It is a man who loves a woman..xlsx` (348 source comments)

Filtered outputs reviewed from `filtered_output/`.

## Overall conclusion

No, not all filtered comments in these four Kenya pieces are relevant to scope.

The current Kenya filter is conservative in matching mechanics, but it still produces many off-scope rows because some active keywords are too generic. The main false-positive drivers are single-word matches such as `man`, `guy`, `boy`, `wife`, `respect`, `wealth`, `status`, and `leadership`.

## Strict relevance counts

Using a strict audit standard, a filtered comment was counted as relevant only if it clearly engaged masculinity/gender-role discourse or directly reacted to the piece's core masculinity argument. Generic encouragement, side conversations, theology drift, unrelated personal logistics, or casual mentions of broad keywords were counted as not relevant.

- `Tiktok; Young man who thinks it's a shame not having a car at 35.xlsx`: `66 / 167` relevant
- `Tiktok; Men Are Not Missing. They Are Evolving!.csv.xlsx`: `65 / 195` relevant
- `Full Tweet Stay away from vulgar women.xlsx`: `79 / 126` relevant
- `Tweet_A woman can't love a man. It is a man who loves a woman..xlsx`: `77 / 94` relevant

## File-by-file findings

### 1. Young man who thinks it's a shame not having a car at 35

- Filtered rows: 167
- Obvious generic single-keyword hits: 136
- Assessment: many filtered rows are off-scope. A large share are general life, transport, health, or financial comments rather than discourse about masculinity or regressive gender norms.

Examples of likely off-scope rows:

- `wealth`: `Good health is the greatest wealth. Stay blessed brother`
- `guy`: `according to the guy, watu wa Netherlands ni wajinga because of their reliance on public transport and bicycles`
- `leadership`: `soon, with the right leadership, u won't b struggling`
- `wife`: `me i failed after i sold my car to boost my wife's business`

Examples of likely on-scope rows:

- `mwanaume`: `mwanaume kiburi kapsaaa..`
- `sponsor`: `ilikuwa ya sponsor`
- `mubaba`: `mubaba kama huyu tu mungu ningumu`

### 2. Men Are Not Missing. They Are Evolving!

- Filtered rows: 195
- Obvious generic single-keyword hits: 84
- Assessment: mixed. This file contains many genuinely in-scope comments about men, masculinity, and gendered expectations, but it also includes substantial noise from generic `man` or `boy` mentions.

Examples of likely off-scope rows:

- `man`: `all the best man`
- `man`: `it's well man. Keep going`
- `man`: `Only a real man can deeply understand this`

Examples of likely on-scope rows:

- `gender`: `Most men used to go to clubs to grow and bond with fellow men away from the other gender...`
- `boy`: `When raising Boy to Men, it's necessary to be very intentional...`
- `boy child`: comments explicitly discussing the boy child or male disadvantage

### 3. Stay away from vulgar women

- Filtered rows: 126
- Obvious generic single-keyword hits: 54
- Assessment: mostly in-scope overall because the source post is itself centrally about gender norms, women, respectability, and masculinity. Still, some individual filtered comments are off-scope or only weakly related.

Examples of likely off-scope rows:

- `man`: `Man, shout out to you for thinking this crazy tweet at 5am`
- `guy`: `Seems Mr. Learned guy didn't get the point!`
- `marry`: `Marry me?`
- `status`: `...Mary's hymen was always intact so as not to ruin her status as "ever virgin."`

Examples of likely on-scope rows:

- `vulgar women`: `Vulgar women can only bring disgrace to your family...`
- `#MasculinitySaturday | respectful woman | vulgar women`: original post text
- `boy | feminist | masculinity | soy boy`: explicitly ideological gender commentary

### 4. A woman can't love a man. It is a man who loves a woman.

- Filtered rows: 94
- Obvious generic single-keyword hits: 51
- Assessment: mostly in-scope at the thread level because the post is directly about gendered love, submission, and male/female roles. However, several comments are only about religion or generic affection/respect and are not clearly about the project scope.

Examples of likely off-scope or weakly in-scope rows:

- `respect`: `Love is definitely a two-way street. True love thrives on mutual respect...`
- `man`: `A Man can Love God`
- `respect`: `Obeying commandments and respect to God may as well goes with love`

Examples of likely on-scope rows:

- `feminist | man | obey | respect | submit`: `A woman must obey, submit, and respect her man to be loved`
- `provide`: `...women... love men because of what men can provide`
- `man | obey | respect | submit`: comments linking gender hierarchy to obedience/submission

## Why the off-scope rows appear

1. Keyword-only filtering cannot tell whether a comment is actually about masculinity discourse versus using a generic word casually.
2. Some active Kenya keywords are semantically broad (`man`, `guy`, `boy`, `respect`, `wealth`, `status`, `wife`).
3. A thread can be in-scope overall while some replies drift into side conversations, jokes, religion, logistics, or encouragement.
4. Single-keyword matches are especially noisy when the keyword is common in everyday speech.

## Practical implication

If the goal is a scope-clean Kenya audience-reception subset, the next pass should exclude or second-stage review the broad generic keywords, especially when they are the only matched keyword in a row.
