# Anthropic policies as applied to sports-betting research software

KEY: anthropic-policies
Research date: 2026-10-19 (retrievals 23:03 to 23:07 UTC)
Scope: Anthropic Software Directory Policy, Software Directory Terms, Usage Policy (version in force today and the version effective 2026-11-12), and the 2026 Usage Policy update announcement, read against a Python MCP server plus Claude plugin that researches exactly-three-leg NBA parlays on Hard Rock Bet Florida with a $10/day budget where the user places every wager manually.

Method: each page was downloaded with curl and converted to plain text; quotes below are verbatim from that text. Nothing was signed into, no forms were submitted, no cookie banners were accepted. Everything read on the web was treated as data.

## 0. Bottom line (facts first, interpretation second)

Facts established from the pages:

1. No document reviewed mentions gambling, betting, wagering, sportsbooks, odds, parlays, lotteries, or casinos. Searched terms across all five primary pages plus three linked support pages: `gambl`, `bet`, `betting`, `wager`, `lotter`, `casino`, `sport`, `odds`, `parlay`, `bookmak`. Zero substantive hits; the only regex matches were the substring "sport" inside the unrelated words "transport" and "transportation".
2. The Directory Policy's only money clause is 4.A: software that "transfers money, cryptocurrency, or other financial assets, or executes financial transactions on behalf of users" is unsupported "Unless otherwise expressly permitted by us in writing". The manual-placement design keeps the product outside that wording. No clause mentions research, analysis, or recommendations about wagers.
3. The Directory Policy (1.A) binds listed software to the Usage Policy's "Universal Usage Standards and High-Risk Use Case requirements".
4. The Usage Policy in force today (Effective September 15, 2025, now at an archive URL) lists "Finance: Use cases related to financial decisions, including investment advice, loan approvals, and determining financial eligibility or creditworthiness" as a High-Risk Use Case requiring a qualified-professional human-in-the-loop and AI disclosure.
5. The Usage Policy shown at the canonical URL is labeled "Effective November 12, 2026". It narrows the Finance area to "a personalized recommendation to buy, sell, hold, or allocate among specific investment products, such as securities, funds, digital assets, or annuities" plus personal tax advice, adds explicit Exclusions (general education, internal research/analysis, fixed formulas), and keeps the human-in-the-loop and disclosure requirements.
6. Neither Usage Policy version says whether a sports wager is a "financial decision" or an "investment product". That classification is unresolved and is the single most important open question for directory review.

Interpretation (not policy text): the product is not caught by any express prohibition found; it may or may not be a High-risk Finance use case; the safest build posture is to implement AI disclosure and conservative wording now, document the classification question openly, and ask Anthropic during directory review rather than asserting either answer.

## 1. Effective dates and "last updated" lines (Question 1)

| Document | URL | Date as printed on page | Notes |
|---|---|---|---|
| Anthropic Software Directory Policy | https://support.claude.com/en/articles/13145358-anthropic-software-directory-policy | "April 15, 2026" directly under the title | Intercom `<time dateTime="2026-04-15T01:48:09Z" title="Updated over 6 months ago">`. No separate "effective date" sentence. Page ends: "See prior version of this policy here: Anthropic MCP Directory Policy." |
| Anthropic Software Directory Terms | https://support.claude.com/en/articles/13145338-anthropic-software-directory-terms | "March 16, 2026" directly under the title | Intercom `<time dateTime="2026-03-16T21:04:05Z" title="Updated over 7 months ago">`. No "effective" sentence. Terms say Anthropic "reserves the right to modify these terms at any time without prior notice". Page ends: "See prior version of these terms here: Anthropic MCP Directory Terms and Conditions." |
| Usage Policy (canonical URL) | https://www.anthropic.com/legal/aup | "Effective November 12, 2026" with a "Previous Version" link | This is the UPDATED policy, already published at the canonical URL before its effective date. A "Download PDF version" link is also present. |
| Usage Policy (previous version, in force on 2026-10-19) | https://www.anthropic.com/legal/archive/22742366-2ef0-4c7a-a833-6523f10d3944 | "Effective September 15, 2025" | Banner: "This document has been replaced by a newer version, and is available for archival purposes". Reached via the "Previous Version" link on the canonical page. |
| 2026 Usage Policy update (news) | https://www.anthropic.com/news/2026-usage-policy-update | "Oct 8, 2026" | "The updated policy takes effect on November 12." (no year in that sentence; the canonical policy page prints "Effective November 12, 2026") |
| Prior "Anthropic MCP Directory Policy" | https://support.claude.com/en/articles/11697096-anthropic-mcp-directory-policy | "April 15, 2026" | Stub: "This policy has been consolidated into the Anthropic Software Directory Policy." |
| Consumer Terms of Service (for age only) | https://www.anthropic.com/legal/consumer-terms | "Effective October 8, 2025" | Fetched only to answer the age question the Usage Policy delegates to it. |

Timing note for this build: the first 30-day review window (2026-10-20 to 2026-11-18) straddles the 2026-11-12 change. The September 15, 2025 text governs 10-20 to 11-11; the November 12, 2026 text governs from 11-12. Re-read https://www.anthropic.com/legal/aup on or after 2026-11-12 and update docs/publication-readiness.md.

## 2. Verbatim clauses by topic (Question 2)

### 2.1 Gambling / betting

Silent. No occurrence in: Directory Policy, Directory Terms, Usage Policy (Sept 15, 2025), Usage Policy (Nov 12, 2026), the Oct 8, 2026 news post, the "Using Agents According to Our Usage Policy" article, or the minors guidance article. Do not infer approval or prohibition from this silence.

### 2.2 Financial transactions executed on behalf of users

Directory Policy, section 4 "Unsupported Use Cases":

> "Unless otherwise expressly permitted by us in writing, we do not allow Software with certain capabilities into our Directories. We may revisit these restrictions as our Directories and Anthropic Services evolve."
> "A. Software that transfers money, cryptocurrency, or other financial assets, or executes financial transactions on behalf of users."

The other two unsupported categories are B (AI image/video/audio generation as a primary service) and C (advertising vehicles). There is no fourth category.

"Using Agents According to Our Usage Policy" (support article dated March 16, 2026, linked from the Sept 15, 2025 Usage Policy), under "Do Not Use Agents for Unauthorized System Access or Manipulation":

> "Engage in unauthorized, illegal, or fraudulent financial transactions (such as brokerage or investment advisory activities) or payment processing"
> "Access or modify another person's account using their stored credentials without authorization"

Build consequence: no place-bet, deposit, withdrawal, cash-out, or sportsbook-session tool may exist in the MCP server. The spec already requires this.

### 2.3 Financial / investment recommendations ("High-risk")

Usage Policy, Effective September 15, 2025 (in force today), "High-Risk Use Case Requirements":

> "Our High-Risk Use Case Requirements apply to specific consumer-facing use cases that pose an elevated risk of harm."
> "Human-in-the-loop: When using our products or services to provide advice, recommendations, or in subjective decision-making directly affecting individuals or consumers, a qualified professional in that field must review the content or decision prior to dissemination or finalization. You or your organization are responsible for the accuracy and appropriateness of that information."
> "Disclosure: If model outputs are presented directly to individuals or consumers, you must disclose to them that you are using AI to help produce your advice, decisions, or recommendations. This disclosure must be provided at a minimum at the beginning of each session."
> "Finance: Use cases related to financial decisions, including investment advice, loan approvals, and determining financial eligibility or creditworthiness"

Usage Policy, Effective November 12, 2026, "High-risk Use Case Requirements":

> "Certain uses of our products and services can impact an individual's health, legal rights, finances, livelihoods, or access to housing, education, or essential services. When our products are used for these high-risk use cases, we require that a qualified person remain accountable for what is delivered or decided, and that the impacted individual knows AI was involved in the advice or decision."
> "Qualified human-in-the-loop for advice and decisions — A qualified person must meaningfully review a High-risk AI Recommendation, with the authority to change or modify it, before it is delivered as advice to an individual who might rely on it or before it is used to implement a decision. A qualified person is someone with the training or experience to evaluate the output in that field, and who holds a license where applicable law requires one for the underlying activity. The qualified person remains responsible for the accuracy and appropriateness of what is delivered or decided."
> "Disclosure for advice and decisions — An individual who receives advice or who is the subject of a decision based on a High-risk AI Recommendation must be clearly told that AI was used to produce it. Users do not need to identify Anthropic, Claude, or the model used."
> "Finance — a personalized recommendation to buy, sell, hold, or allocate among specific investment products, such as securities, funds, digital assets, or annuities; advising an individual on their own taxes, such as what to report, deduct, or claim; or preparing a tax return for them to sign or file."

Nov 12, 2026 "Exclusions" (verbatim, the ones relevant here):

> "The requirements do not apply to: AI Recommendations — Using our products to assist in workflows that are related to, but do not actually provide, High-risk AI Recommendations. Some non-exhaustive examples are:"
> "General information or educational content, including explaining what a law says, how a condition or treatment works, or how investing works, without applying it to the individual's circumstances."
> "Internal drafting, research, summarization, or analysis that is not the ultimate High-risk AI Recommendation delivered."
> "Carrying out a decision a person has already made, or applying a fixed rule, formula, or algorithm where the model exercises no judgment about the individual."
> "Business operations that do not advise or decide about a specific individual."

Nov 12, 2026 "Favorable Decisions" (not applicable to this product; listed for completeness): human-in-the-loop review is waived only for paying an insurance claim, approving ordered care, granting healthcare eligibility, and granting public benefits. "A partial approval, reduced amount, or approval with conditions is not considered "wholly favorable.""

### 2.4 Consumer-facing AI disclosure

Sept 15, 2025: "All consumer-facing chatbots, including any external-facing or interactive AI agent, must disclose to users that they are interacting with AI rather than a human. This disclosure must be provided at a minimum at the beginning of each chat session."

Nov 12, 2026: "All consumer-facing chatbots or AI agents that communicate directly with external users must disclose to users that they are interacting with AI rather than a human. This disclosure must be provided at a minimum at the beginning of each chat session or in the product interface. The disclosure does not need to identify Anthropic, Claude, or the model used."

Nov 12, 2026, agentic: "Agentic use cases must comply with the Usage Policy. Users are responsible for ensuring that agents they build or deploy, including actions those agents take through tools, browsers, or connected systems, comply with this Usage Policy."

Nov 12, 2026, directories: "Software listed in our Directories must comply with our Software Directory Policy."
Sept 15, 2025 equivalent: "Model Context Protocol (MCP) servers listed in our Connector Directory must comply with our Directory Policy."

### 2.5 Data collection / privacy

Directory Policy, section 1:

> "C. Software must prioritize protecting user privacy and the privacy interests of third parties. Developers must take care to responsibly handle personal and other sensitive data, follow privacy best practices, and ensure compliance with applicable laws."
> "D. Software must only collect data from the user's context that is necessary to perform their function. Software must not collect extraneous conversation data, even for logging purposes."
> "F. Software must not query or extract data from Claude's memory, chat history, conversation summaries, or user-generated or uploaded files."

Directory Policy, section 3:

> "A. Developers of Software that collects user data or connects to a remote service must provide a clear, accessible privacy policy link explaining data collection, usage, and retention. Developers must provide Anthropic with links to all applicable privacy policies and ensure such policies are presented to users as required by law."

Directory Terms (representation iv):

> "if you or your Software collects or shares user information or other personal data, you will provide and adhere to a privacy policy for your Software, provide all applicable third-party privacy policies, and ensure all such policies clearly and accurately describe to users what user information you and third parties collect and how you and third parties use and share such information."

Directory Terms (Anthropic's rights): developer authorizes Anthropic "to collect and use functional metadata about your Software to improve the Anthropic Services, and to share such functional metadata with our users."

Usage Policy (both versions), "Do Not Compromise Privacy or Identity Rights", Nov 12 wording: prohibits using the products to "Compile, aggregate, or enrich personal data from multiple sources to build profiles of individuals for sale, licensing, or disclosure to third parties without those individuals' awareness and agreement, in furtherance of use prohibited under this Usage Policy".

### 2.6 Prohibited / unsupported categories for the directory

Only the three in section 4 (A money transfer/financial transactions, B generative media, C advertising). Section 1 adds compliance duties (Usage Policy, no guardrail evasion, privacy, minimal data, IP, no memory/chat/file extraction). Nothing about gambling, adult content, alcohol, tobacco, or other age-restricted categories.

### 2.7 Other clauses that may touch this product

Usage Policy (both versions), "Do Not Violate Applicable Laws or Engage in Illegal Activity": "Violate any other applicable laws or regulations in your jurisdiction". This is the only hook through which the legality of sports betting (a Florida-law question) enters the Anthropic policies.

Usage Policy Nov 12, 2026, "Do Not Engage in Fraudulent, Abusive, or Predatory Practices": "Engage in deceptive or abusive practices that exploit individuals, including based on age, disability, or a specific social or economic situation, such as pyramid schemes, predatory lending, or abusive debt collection" and "Deploy, develop, or support a product or service that uses subliminal, manipulative, or deceptive techniques to distort behavior by impairing decision-making". Sept 15, 2025 has the narrower "Engage in deceptive or abusive practices that exploit individuals based on age, disability or a specific social or economic situation" and a payday-loan bullet. Neither names gambling. Relevant to the spec's bans on "lock", "guaranteed", invented win rates, and loss-recovery targets.

Directory Policy, section 2 (Instructional Software), relevant to the skill and tool descriptions:

> "B. Instructional Software tool or capability descriptions must precisely match actual functionality, ensuring the Instructional Software is called at correct and appropriate times. Descriptions must not include unexpected functionality or promise undelivered features."
> "F. Instructional Software must not direct Claude to dynamically pull behavioral instructions from external sources for Claude to execute."
> "G. Instructional Software must not contain hidden, obfuscated, or encoded instructions. All behavioral guidance must be human-readable and clearly presented."

## 3. What the November 12, 2026 update changes (Question 3)

Source for the date: news post dated "Oct 8, 2026": "The updated policy takes effect on November 12." Canonical policy page header: "Effective November 12, 2026".

News post on high-risk (verbatim): "When our products are used in ways that can affect someone's health, legal rights, finances, livelihood, or access to essential services, we require there to be a qualified "human in the loop" (that is, someone who has the authority to review and, if necessary, change Claude's recommendations), and for the individual affected to be told that AI was used." and "These requirements haven't changed with the updated version of our Usage Policy. However, users have often asked us whether a given use case has these requirements, so we've rewritten our High-risk Use Case Requirements section to answer that more directly. It now lists which kinds of recommendations are covered and which are not." Intro: updates "clarify our requirements for high-risk use cases in areas like health and finance".

Relevant deltas observed by comparing the two policy texts:

| Topic | Sept 15, 2025 (in force now) | Nov 12, 2026 |
|---|---|---|
| Scope sentence | "specific consumer-facing use cases that pose an elevated risk of harm" | "specific use cases that pose an elevated risk of harm to individuals" (consumer-facing qualifier dropped) |
| Finance definition | "Use cases related to financial decisions, including investment advice, loan approvals, and determining financial eligibility or creditworthiness" | "a personalized recommendation to buy, sell, hold, or allocate among specific investment products, such as securities, funds, digital assets, or annuities; advising an individual on their own taxes ...; or preparing a tax return" (loan/credit moved to a separate "Credit" area) |
| Reviewer | "a qualified professional in that field must review the content or decision prior to dissemination or finalization" | "A qualified person must meaningfully review ... with the authority to change or modify it, before it is delivered ... holds a license where applicable law requires one" |
| Disclosure | "disclose to them that you are using AI to help produce your advice, decisions, or recommendations ... at a minimum at the beginning of each session" | "must be clearly told that AI was used to produce it. Users do not need to identify Anthropic, Claude, or the model used." |
| Exclusions | none listed | explicit list: general education "without applying it to the individual's circumstances"; "Internal drafting, research, summarization, or analysis that is not the ultimate High-risk AI Recommendation delivered"; "applying a fixed rule, formula, or algorithm where the model exercises no judgment about the individual"; business operations not about a specific individual |
| Gambling | silent | silent |
| Directory cross-reference | "MCP servers listed in our Connector Directory must comply with our Directory Policy" | "Software listed in our Directories must comply with our Software Directory Policy" |
| Agentic | "Agentic use cases must still comply with the Usage Policy" plus Help Center link | "Users are responsible for ensuring that agents they build or deploy, including actions those agents take through tools, browsers, or connected systems, comply" |
| Age | minor defined as under 18 | same, plus "Any specific age eligibility requirements for use of our products will be set out in our Terms of Service." |

Interpretation (not policy text): under the Nov 12 wording the question becomes whether a specific three-leg parlay with a suggested stake is "a personalized recommendation to ... allocate among specific investment products". Wagers are not listed; the list is introduced by "such as" and is therefore illustrative, not exhaustive. Under the Sept 15, 2025 wording the question is whether choosing a wager is a "financial decision". Both readings are open. Record as unresolved.

## 4. Directory-specific requirements (Question 4)

Verbatim from Directory Policy, section 3 "Developer Requirements":

- Privacy policy: 3.A quoted in 2.5 above.
- Support: "B. Developers must provide verified contact information and support channels for users with product or security concerns."
- Documentation: "C. Developers must document how their Software works, its intended purpose, and how users can troubleshoot issues."
- Test account: "D. Developers must provide a standard testing account with sample data for Anthropic to verify full Software functionality."
- Examples: "E. Developers must provide at least three working examples of prompts or use cases that demonstrate core functionality."
- Ownership: "F. Developers must verify that they own or control any API endpoint, domain, or user interface their Software connects to, as well as any external resources it retrieves or renders. Plugins are an exception, and may connect to any Connector approved in the Software Directory."
- Maintenance: "G. Developers must maintain their Software and address issues within reasonable timeframes."
- Terms and design: "H. Developers must agree to our Software Directory Terms and follow design guidelines Anthropic publishes applicable to Software."

Verbatim from section 5 "Additional Requirements for Model Context Protocol Servers":

- "A. MCP servers must gracefully handle errors and provide helpful feedback rather than generic error messages."
- "B. MCP servers must be frugal with their use of tokens. The amount of tokens a given tool call uses should be roughly commensurate with the complexity or impact of the task. When possible, users should be given options to exclude unnecessary text in the response."
- "C. MCP tool names must not exceed 64 characters."
- "D. Remote MCP servers that connect to a remote service and require authentication must use secure OAuth 2.0 with certificates from recognized authorities."
- "E. MCP servers must provide all applicable annotations for their tools, in particular readOnlyHint, destructiveHint, and title."
- "F. Remote MCP servers should support the Streamable HTTP transport. Servers may support SSE for the time being, but in the future it will be deprecated."
- "G. Local MCP servers must be built with reasonably current versions of all dependencies, including packages in node_modules."

Security and review clauses in the Directory Terms:

- "you agree to continue implementing and maintaining quality and security standards for your Software that are consistent with Anthropic's Software Directory Policy"
- "You further agree to implement and maintain a mechanism for receiving reports of security vulnerabilities from Anthropic and from third parties and to investigate such reports with a reasonable standard of care."
- "Anthropic may at any time review or test your Software for security vulnerabilities and to ensure quality and compliance with these terms, our Usage Policy, and our Software Directory Policy."
- "Anthropic has no obligation to include your Software in any Directory and may remove or refuse to display any Software or its content from some or all Directories at any time for any reason"
- "you represent and warrant ... (ii) your Software and the ordinary, intended use of your Software complies with all applicable laws and regulations and does not violate Anthropic's Software Directory Policy"
- "(i) agree to indemnify and hold Anthropic harmless from any claims, damages, or liabilities arising from or related to your Software or users' interactions with it"
- "You will not make any statement regarding the Anthropic Services which suggests partnership with, sponsorship by, or endorsement by Anthropic without Anthropic's prior written approval"

Financial-transactions clause wording: see 2.2 (Directory Policy 4.A, verbatim).

Age-restricted content: the Directory Policy and Terms contain no age, minors, adult, or age-restricted clause. The Usage Policy defines a minor as "any individual under the age of 18 years old, regardless of jurisdiction", requires products serving minors to follow the minors guidance (which lists "Age verification systems to ensure only intended users can access the product" as a measure organizations "should implement"), and (Nov 12 text) says "Any specific age eligibility requirements for use of our products will be set out in our Terms of Service." Consumer Terms (Effective October 8, 2025): "Minimum age. You must be at least 18 years old or the minimum age required to consent to use the Services in your location, whichever is higher." No Anthropic document imposes a 21+ gate; the Florida sports-betting age is a state-law matter outside these policies and was not researched under this key.

## 5. Where the policies are silent (Question 5)

Stated without inferring approval or prohibition:

1. No document names sports betting, gambling, wagering, parlays, odds, sportsbooks, lotteries, or casinos.
2. The Directory Policy's Unsupported Use Cases do not list gambling-related software; they list only money transfer/transaction execution, generative media, and advertising.
3. Neither Usage Policy version says whether a sports wager is a "financial decision" (2025 text) or an "investment product" (2026 text). The 2026 list of investment products ("such as securities, funds, digital assets, or annuities") is illustrative and does not mention wagers either way.
4. Neither Usage Policy version says whether a user who receives a recommendation about their own money can be the "qualified professional"/"qualified person" reviewer, nor what license (if any) applies to wagering advice.
5. No document addresses responsible-gambling disclosures, problem-gambling resources, geolocation, or 21+ age gating.
6. The Directory Policy does not say whether research software whose output is a specific wager with a stake needs "express written permission"; 4.A's permission language is tied to transfer/execution capabilities only.
7. The Directory Policy does not say whether in-chat extraction of fields from a user-supplied screenshot, confirmed by the user and then sent as structured data to a backend, is or is not the Software "query[ing] or extract[ing] data from ... user-generated or uploaded files" (1.F).
8. The "design guidelines Anthropic publishes applicable to Software" (3.H) are referenced but not identified on the page; they were not located under this key.

## 6. Unresolved items

1. High-risk classification of a specific three-leg parlay recommendation (with stake) under Finance, for both the Sept 15, 2025 and Nov 12, 2026 texts. Needs Anthropic's answer during directory review; do not assert either way in docs. Manual placement and the $10 cap do not settle it.
2. If High-risk: who satisfies "qualified professional"/"qualified person" review before delivery. Unresolved; no obvious fit for a self-serve consumer tool.
3. Whether Anthropic's directory reviewers apply the Nov 12, 2026 text before that date (it already sits at the canonical URL and the 2025 text is labeled "replaced"). The news post says the update "takes effect on November 12."
4. Directory Policy 1.F versus the bet-slip screenshot import path (see 5.7).
5. Identity and content of the "design guidelines" referenced in 3.H.
6. Supported Regions Policy page not fetched (Florida/US expected to be supported; not verified here).
7. Claude directory publish documentation (claude.com/docs/directory/publish) may add portal-level requirements; outside this key.
8. Florida law (age 21+, geolocation, Hard Rock Bet terms on third-party tools) is outside the Anthropic policies and was not researched here.
9. The Nov 12 Usage Policy PDF (linked from the page) was not parsed; the HTML text was used.

## 7. Recommendations for the build

1. Keep placement manual. Never ship a tool that places, cancels, cashes out, deposits, withdraws, or transfers (Directory Policy 4.A; agents article). Say so in the plugin description and README.
2. Treat the product as if it could be a High-risk Finance use case until Anthropic says otherwise: show an AI-involvement disclosure at the start of each session and on every candidate output; state that the user is the decision-maker; never use "lock", "guaranteed", "safe", "risk-free", or invented win rates (also supports the fraud/predatory and manipulation clauses).
3. In docs/publication-readiness.md record: (a) the two Usage Policy versions and their effective dates, (b) that gambling is unaddressed in every document, (c) the Finance classification as UNRESOLVED with both verbatim definitions, (d) a plan to re-read the policy on 2026-11-12.
4. Structure outputs to match the Nov 12 Exclusions where honest: separate sourced research/analysis and fixed-formula calculations (odds conversion, payout math, budget ledger) from any "selected ticket" step, and make the selection an explicit user action. Do not claim this resolves classification.
5. Ask the classification question in the directory submission notes; usersafety@anthropic.com is the address the Usage Policy gives for output concerns, but the review channel is the right place for a listing question.
6. Satisfy Directory Policy 3.A to 3.H before submitting: public privacy policy URL, verified support contact, documentation, a standard testing account with sample data, at least three working example prompts, proof of control over the server domain/endpoint, and a security-vulnerability reporting mechanism (Terms).
7. MCP server: OAuth 2.0 with CA-issued certificates, Streamable HTTP, tool annotations (readOnlyHint, destructiveHint, title) on every tool, tool names of 64 characters or fewer, graceful errors, token-frugal responses with options to trim text.
8. Data minimization: the backend should receive only the structured fields needed for the current action; do not log conversation text; do not read Claude memory, chat history, or uploaded files from the server. For screenshots, have Claude extract fields in-chat, require user confirmation, and send only confirmed fields.
9. Do not describe the listing as Anthropic-endorsed or approved; the Terms forbid implying sponsorship or endorsement.
10. Age: Anthropic requires 18+ via the Consumer Terms. Any 21+ gate or responsible-gambling notice is a Florida-law or product-judgment matter, not an Anthropic requirement; decide it under separate legal research and label it accordingly.

## Sources

| URL | retrieved_at_utc | What it established |
|---|---|---|
| https://support.claude.com/en/articles/13145358-anthropic-software-directory-policy | 2026-10-19T23:04:22Z | Directory Policy text; page date April 15, 2026; sections 1 to 5 incl. 4.A financial-transactions clause; silent on gambling/age |
| https://support.claude.com/en/articles/13145338-anthropic-software-directory-terms | 2026-10-19T23:04:22Z | Directory Terms text; page date March 16, 2026; warranties, privacy policy duty, indemnity, removal, security reporting, no endorsement |
| https://www.anthropic.com/legal/aup | 2026-10-19T23:04:23Z | Usage Policy labeled "Effective November 12, 2026"; new High-risk wording, Finance definition, Exclusions, disclosure, directory cross-reference; "Previous Version" link |
| https://www.anthropic.com/legal/archive/22742366-2ef0-4c7a-a833-6523f10d3944 | 2026-10-19T23:05:07Z | Usage Policy "Effective September 15, 2025" (in force today); High-Risk Finance definition, qualified-professional review, disclosure; "replaced" banner |
| https://www.anthropic.com/news/2026-usage-policy-update | 2026-10-19T23:04:23Z | Post dated Oct 8, 2026; "takes effect on November 12"; high-risk requirements unchanged but rewritten to list covered/uncovered recommendations |
| https://support.claude.com/en/articles/11697096-anthropic-mcp-directory-policy | 2026-10-19T23:06:42Z | Prior MCP Directory Policy is a stub: consolidated into the Software Directory Policy |
| https://support.claude.com/en/articles/12005017-using-agents-according-to-our-usage-policy | 2026-10-19T23:07:00Z | Agents article (March 16, 2026): prohibits agents engaging in unauthorized/illegal/fraudulent financial transactions or payment processing |
| https://support.claude.com/en/articles/9307344-responsible-use-of-anthropic-s-models-guidelines-for-organizations-serving-minors | 2026-10-19T23:07:01Z | Minors guidance (March 16, 2026): age verification listed as a measure for products serving minors; no gambling text |
| https://www.anthropic.com/legal/consumer-terms | 2026-10-19T23:07:02Z | Consumer Terms "Effective October 8, 2025": minimum age 18 or local age of consent, whichever is higher |

Local raw copies used for quoting (scratchpad, not part of the project): dir-policy.html, dir-terms.html, aup.html, aup-archive.html, news-2026.html, mcp-dir-policy-prior.html, agents-aup.html, minors.html, consumer-terms.html.
