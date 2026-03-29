# Base Agent Catalog — Research & Implementation Plan

## Problem Statement

Swarm's orchestrator encourages specialization ("clone a base agent and narrow it") but the registry is empty — there are no base agents to clone from. Plan templates reference agent types (`architect`, `code-reviewer`, `technical-writer`) that don't exist. Every new task requires creating agents from scratch, defeating the purpose of the registry.

## Goal

Create a curated catalog of **66 base agents** across three domains (technical, general-purpose, business) with **174 specialization examples**, plus update Swarm's orchestrator and forge to actively guide users toward cloning from this catalog.

## Design Principles

- **Three-domain coverage**: Technical (software dev), General (life/productivity), Business (startup through operations)
- **Separation of concerns**: Producers and reviewers are never the same agent
- **Output-oriented**: Each agent defines its expected output format
- **Tool-aware**: Each agent declares recommended tools (loose suggestions, not enforcement)
- **Clone-friendly**: System prompts use specialization hooks so customization is additive, not destructive
- **Specialization ladder**: base → domain-specific → project-specific

---

## Decisions

1. **Base agents are read-only.** Packaged with Swarm, immutable in registry. Users clone to customize.
2. **Parent-update flagging (Option B).** Clones are independent, but get flagged when their parent base agent is updated in a new Swarm release. Tracked via existing `parent_id` chain.
3. **Model preferences are set per base agent, but user can override at plan time.** E.g., `critic` defaults to Opus, `code-researcher` defaults to Haiku.
4. **Tools are loose suggestions, not enforcement.** Base agents declare recommended tools; orchestrator adjusts at plan time.
5. **Template agent types renamed to match base agent names (Option A).** Simple, direct, no indirection layer.
6. **Existing test agents removed.** Registry cleaned out — fresh start for the base catalog.

---

## The Catalog

### Domain 1: Technical (24 base agents)

#### Discovery & Analysis
| # | Agent | Role |
|---|-------|------|
| 1 | `code-researcher` | Explores codebases, reads files, traces dependencies, gathers technical context |
| 2 | `online-researcher` | Searches the web, reads documentation sites, synthesizes findings from online sources |
| 3 | `requirements-analyst` | Breaks goals into structured requirements and acceptance criteria |
| 4 | `code-analyzer` | Static analysis — reads code structure, dependencies, complexity metrics |

#### Design & Architecture
| # | Agent | Role |
|---|-------|------|
| 5 | `architect` | Designs system structure, data models, APIs, component boundaries |
| 6 | `planner` | Creates step-by-step implementation plans with dependencies and risks |
| 7 | `data-modeler` | Designs data schemas, entity relationships, normalization, serialization formats |

#### Implementation
| # | Agent | Role |
|---|-------|------|
| 8 | `implementer` | Writes production code following specs and designs |
| 9 | `refactorer` | Improves code structure without changing behavior |

#### Testing & Quality
| # | Agent | Role |
|---|-------|------|
| 10 | `test-writer` | Creates comprehensive test suites (unit, integration, e2e) |
| 11 | `code-reviewer` | Reviews code for quality, bugs, patterns, readability |
| 12 | `debugger` | Diagnoses and fixes bugs from error reports and failing tests |

#### Security & Performance
| # | Agent | Role |
|---|-------|------|
| 13 | `security-auditor` | Reviews code for security vulnerabilities and best practices |
| 14 | `performance-analyst` | Identifies bottlenecks and optimization opportunities |
| 15 | `accessibility-auditor` | WCAG compliance, screen reader testing, keyboard navigation, color contrast |

#### Documentation
| # | Agent | Role |
|---|-------|------|
| 16 | `technical-writer` | Creates documentation, guides, API references |
| 17 | `summarizer` | Synthesizes outputs from multiple agents into actionable reports |

#### Infrastructure & Operations
| # | Agent | Role |
|---|-------|------|
| 18 | `devops-engineer` | Infrastructure, deployment pipelines, CI/CD, monitoring setup |
| 19 | `incident-responder` | Triage, root cause diagnosis, stakeholder comms, post-mortems |
| 20 | `ops-automator` | Designs automation for repetitive tasks — scripts, schedules, triggers, monitoring |

#### Meta / Orchestration
| # | Agent | Role |
|---|-------|------|
| 21 | `critic` | Reviews any agent's output for quality, completeness, accuracy |
| 22 | `prompt-engineer` | Crafts, tests, and iterates on LLM prompts — structure, few-shot examples, guardrails |
| 23 | `ux-analyst` | Evaluates user flows, identifies friction points, proposes UX improvements |
| 24 | `compliance-checker` | Evaluates work against standards, regulations, and policies — flags violations |

### Domain 2: General Purpose (28 base agents)

#### Planning & Strategy
| # | Agent | Role |
|---|-------|------|
| 25 | `strategic-planner` | Long-term goal setting, milestones, priority frameworks, progress tracking |
| 26 | `event-planner` | Event logistics — timelines, checklists, venues, vendors, contingencies |
| 27 | `project-coordinator` | Task breakdown, timelines, dependency tracking, status reporting, delegation |
| 28 | `workflow-designer` | Designs multi-step processes, SOPs, automation sequences, handoff points |
| 29 | `prioritizer` | Ranks items by impact, effort, urgency, and dependencies — cuts scope ruthlessly |
| 30 | `estimator` | Provides time/cost/effort estimates with confidence ranges and assumption lists |
| 31 | `change-manager` | Plans organizational/technical change — stakeholder mapping, communication plans, rollout phases |

#### Analysis & Decision-Making
| # | Agent | Role |
|---|-------|------|
| 32 | `decision-analyst` | Structured decision-making — pros/cons matrices, risk weighting, scenario analysis |
| 33 | `risk-assessor` | Identifies risks, scores likelihood/impact, proposes mitigations, tracks residual risk |
| 34 | `competitor-analyst` | Competitive landscape mapping, feature comparison, positioning, SWOT |
| 35 | `business-analyst` | Process mapping, requirements gathering, stakeholder alignment, gap analysis |
| 36 | `data-interpreter` | Reads data (CSVs, tables, reports), finds patterns, explains trends in plain language |
| 37 | `fact-checker` | Verifies claims against sources, flags unsupported assertions, rates confidence |

#### Communication & Writing
| # | Agent | Role |
|---|-------|------|
| 38 | `creative-writer` | Versatile writing — narratives, copy, speeches, pitches, tone adaptation |
| 39 | `communication-drafter` | Emails, messages, announcements, difficult conversations, tone calibration |
| 40 | `editor` | Proofreading, style consistency, clarity improvement, tone adjustment, brevity |
| 41 | `presentation-designer` | Slide structure, visual hierarchy, storytelling flow, audience calibration |
| 42 | `translator` | Translates content between languages preserving tone, idiom, and domain terminology |
| 43 | `negotiation-strategist` | Prepares negotiation positions — BATNA, anchoring, concession planning, scripts |
| 44 | `mediator` | Resolves conflicts between competing viewpoints — finds common ground, proposes compromises |

#### Learning & Growth
| # | Agent | Role |
|---|-------|------|
| 45 | `tutor` | Explains concepts at the right level, asks comprehension questions, scaffolds learning |
| 46 | `learning-designer` | Study plans, skill roadmaps, curriculum sequencing, knowledge gap analysis |
| 47 | `coach` | Motivational guidance, accountability, habit formation, mindset, progress celebration |
| 48 | `interviewer` | Conducts structured interviews — asks questions, follows up, evaluates responses |

#### Finance & Legal
| # | Agent | Role |
|---|-------|------|
| 49 | `financial-analyst` | Budgets, cost analysis, forecasting, ROI, comparison shopping |
| 50 | `contract-reviewer` | Reads contracts/agreements, flags risks, summarizes terms, suggests amendments |
| 51 | `advisor` | General counsel with structured reasoning — weighs trade-offs, asks clarifying questions |
| 52 | `brainstormer` | Ideation, lateral thinking, option generation, mind mapping, "what if" exploration |

### Domain 3: Business — Start & Run (14 base agents)

#### Startup & Strategy
| # | Agent | Role |
|---|-------|------|
| 53 | `business-plan-writer` | Business plans — executive summary, market analysis, financial projections, competitive positioning |
| 54 | `brand-designer` | Brand identity — naming, positioning, voice/tone guidelines, taglines, visual direction briefs |
| 55 | `investor-relations-manager` | Pitch materials, investor updates, cap table explanation, fundraising timeline, due diligence prep |
| 56 | `growth-strategist` | Scaling playbooks, unit economics, growth levers, market expansion, partnership strategy |
| 57 | `product-manager` | Feature prioritization, roadmapping, user story writing, stakeholder alignment, launch planning |

#### Sales & Marketing
| # | Agent | Role |
|---|-------|------|
| 58 | `sales-strategist` | Sales pipelines, outreach strategy, qualification frameworks, objection handling, close techniques |
| 59 | `marketing-strategist` | Channel selection, campaign design, funnel optimization, messaging, audience segmentation |
| 60 | `customer-researcher` | Customer interviews, persona development, journey mapping, pain point identification, NPS analysis |
| 61 | `customer-success-manager` | Retention strategy, satisfaction surveys, feedback loops, churn analysis, upsell identification |

#### Operations & Finance
| # | Agent | Role |
|---|-------|------|
| 62 | `operations-manager` | Process design, efficiency optimization, vendor management, quality control, capacity planning |
| 63 | `bookkeeper` | Transaction categorization, reconciliation, financial statements, cash flow tracking |
| 64 | `tax-strategist` | Tax-advantaged structures, deduction maximization, quarterly planning, entity-type implications |
| 65 | `hr-manager` | Hiring, onboarding, policies, handbook drafting, compliance, performance management |
| 66 | `legal-advisor` | Entity formation, contract basics, IP protection, regulatory requirements, liability reduction |

---

## Specialization Examples (174)

### Technical Specializations (73)

#### From `code-researcher`
| Agent | What it adds |
|-------|-------------|
| `dependency-researcher` | Maps dependency trees, finds version conflicts, license issues |
| `migration-researcher` | Audits codebase for migration readiness (e.g., Python 2→3, React class→hooks) |
| `api-surface-researcher` | Maps public API surface — endpoints, contracts, breaking change risk |

#### From `online-researcher`
| Agent | What it adds |
|-------|-------------|
| `library-researcher` | Evaluates libraries/frameworks — stars, maintenance, alternatives, tradeoffs |
| `cve-researcher` | Searches CVE databases, security advisories, patch availability |
| `docs-researcher` | Reads upstream docs, SDK references, changelog entries for specific questions |

#### From `architect`
| Agent | What it adds |
|-------|-------------|
| `api-architect` | REST/GraphQL endpoint design, versioning strategy, schema evolution |
| `database-architect` | Schema design, normalization, indexing strategy, migration safety |
| `event-driven-architect` | Message queues, event schemas, saga patterns, eventual consistency |
| `websocket-designer` | Connection lifecycle, reconnection strategy, message schema, backpressure |
| `rate-limiter-designer` | Token bucket/sliding window, per-tenant limits, graceful degradation |
| `feature-flag-designer` | Flag lifecycle, gradual rollout, kill switches, tech debt cleanup scheduling |
| `api-versioning-strategist` | URL vs header versioning, sunset policies, backward compat |
| `ml-pipeline-designer` | Training pipelines, feature stores, model versioning, A/B test infrastructure |

#### From `implementer`
| Agent | What it adds |
|-------|-------------|
| `python-implementer` | Python idioms, type hints, async/await, packaging conventions |
| `typescript-implementer` | TS strict mode, generics, discriminated unions, module patterns |
| `sql-implementer` | Writes migrations, stored procedures, complex queries, CTEs |
| `cli-implementer` | CLI tools — argument parsing, help text, exit codes, stdin/stdout |
| `dockerfile-writer` | Multi-stage builds, layer optimization, security hardening, distroless bases |
| `terraform-writer` | HCL modules, state management, provider patterns, drift detection |
| `etl-implementer` | Data pipelines, transformation logic, idempotency, backfill strategies |
| `regex-writer` | Pattern construction, edge case testing, readability, backtracking avoidance |
| `mobile-implementer` | React Native / Flutter patterns, offline-first, deep linking, push notifications |
| `database-migration-writer` | Safe migrations, zero-downtime DDL, data backfills, rollback scripts |
| `code-migration-writer` | Codemods, AST transforms, find-and-replace at scale, migration verification |

#### From `refactorer`
| Agent | What it adds |
|-------|-------------|
| `css-refactorer` | Design token extraction, specificity cleanup, responsive breakpoint consolidation |
| `dependency-updater` | Version bumps, breaking change assessment, test verification, lock file hygiene |
| `extract-service-refactorer` | Decomposing monoliths — finding boundaries, extracting modules/services |
| `dead-code-refactorer` | Finds and removes unused code, unreachable paths, stale feature flags |

#### From `test-writer`
| Agent | What it adds |
|-------|-------------|
| `pytest-writer` | pytest fixtures, parametrize, mocking, conftest patterns |
| `integration-test-writer` | API contract tests, database fixtures, service stubs, docker compose |
| `playwright-test-writer` | E2E browser tests, page objects, network interception, visual regression |
| `api-test-writer` | Contract tests, status code coverage, auth edge cases, rate limit testing |
| `load-test-writer` | k6/Locust scripts, traffic shaping, baseline establishment, bottleneck identification |
| `test-fixture-designer` | Factory patterns, realistic fake data, database seeding, state isolation |
| `chaos-test-designer` | Failure injection, blast radius scoping, steady-state hypothesis, game day plans |

#### From `code-reviewer`
| Agent | What it adds |
|-------|-------------|
| `python-reviewer` | PEP8, type annotation coverage, pythonic patterns, common gotchas |
| `concurrency-reviewer` | Race conditions, deadlocks, async pitfalls, thread safety |
| `api-contract-reviewer` | Breaking changes, backward compatibility, versioning discipline |
| `accessibility-reviewer` | ARIA attributes, semantic HTML, focus management, screen reader flow |
| `error-handling-reviewer` | Exception hierarchy, retry logic, graceful degradation, error messages |
| `logging-reviewer` | Structured logging, log levels, PII redaction, correlation IDs |
| `i18n-reviewer` | String externalization, pluralization, RTL support, date/number formatting |
| `config-reviewer` | Environment separation, secret management, sensible defaults, 12-factor |

#### From `security-auditor`
| Agent | What it adds |
|-------|-------------|
| `owasp-auditor` | OWASP Top 10 — injection, XSS, CSRF, auth bypass |
| `secrets-auditor` | Hardcoded credentials, .env leaks, key rotation, vault patterns |
| `secrets-manager-designer` | Vault patterns, rotation schedules, least-privilege, audit logging |
| `dependency-auditor` | License compliance, transitive risk, supply chain verification, SBOM |
| `network-security-reviewer` | Firewall rules, mTLS, CORS policies, CSP headers, egress filtering |

#### From `performance-analyst`
| Agent | What it adds |
|-------|-------------|
| `sql-performance-analyst` | Query plans, index usage, N+1 detection, connection pooling |
| `memory-profiler` | Memory leaks, allocation patterns, GC pressure, object lifecycle |
| `caching-strategist` | Cache invalidation, TTL tuning, stampede prevention, layer design |

#### From `technical-writer`
| Agent | What it adds |
|-------|-------------|
| `api-documenter` | OpenAPI specs, endpoint examples, auth docs, error catalogs |
| `runbook-writer` | Operational runbooks — incident response, deployment steps, rollback |
| `changelog-writer` | Conventional commits, semver reasoning, migration guides, breaking changes |
| `error-message-writer` | User-facing error copy, error codes, troubleshooting links |
| `code-commenter` | Inline docs, docstrings, JSDoc/typedoc, "why" not "what" style |

#### From `devops-engineer`
| Agent | What it adds |
|-------|-------------|
| `ci-cd-designer` | GitHub Actions / GitLab CI, caching, matrix builds, deployment gates |
| `monitoring-designer` | Alerting rules, dashboard layouts, SLI/SLO definition, runbook linking |
| `kubernetes-reviewer` | Resource limits, pod security, network policies, helm chart review |
| `sla-designer` | SLI definition, error budget calculation, alerting thresholds |
| `backup-strategist` | RPO/RTO targets, backup scheduling, restore testing, disaster recovery |
| `github-actions-designer` | Workflow composition, reusable actions, matrix strategies, OIDC auth |

#### From `incident-responder`
| Agent | What it adds |
|-------|-------------|
| `incident-post-mortem-writer` | Blameless format, timeline reconstruction, contributing factors |

#### From `planner`
| Agent | What it adds |
|-------|-------------|
| `release-planner` | Release checklists, rollback plans, feature flag sequencing, canary strategies |

#### From `workflow-designer`
| Agent | What it adds |
|-------|-------------|
| `git-workflow-designer` | Branching strategies, PR templates, merge policies, hook automation |

#### From `data-modeler`
| Agent | What it adds |
|-------|-------------|
| `graphql-schema-designer` | Resolver patterns, N+1 prevention, federation boundaries, deprecation |
| `openapi-spec-writer` | OpenAPI 3.1, schema components, example generation, SDK-friendly design |
| `search-index-designer` | Elasticsearch/Algolia mappings, tokenization, relevance tuning |

#### From `prompt-engineer`
| Agent | What it adds |
|-------|-------------|
| `prompt-optimizer` | Token reduction, structured output reliability, hallucination prevention |
| `system-prompt-writer` | Role definition, constraint specification, output format enforcement |

#### From `critic`
| Agent | What it adds |
|-------|-------------|
| `test-coverage-critic` | Missing edge cases, mutation testing gaps, assertion strength |
| `data-validator` | Schema validation, data quality rules, anomaly detection, completeness |

### General-Purpose Specializations (63)

#### From `strategic-planner`
| Agent | What it adds |
|-------|-------------|
| `life-goals-planner` | Personal goal frameworks (health, finance, relationships), quarterly reviews |
| `fitness-planner` | Workout programming, progressive overload, recovery scheduling |
| `habit-tracker-designer` | Habit stacking, cue-routine-reward design, streak tracking, friction reduction |
| `meal-planner` | Weekly meal plans, grocery lists, dietary constraints, prep time optimization |
| `garden-planner` | Zone matching, companion planting, seasonal calendar, space optimization |
| `pet-care-planner` | Vet schedules, nutrition planning, training milestones, emergency prep |
| `wardrobe-planner` | Capsule wardrobe design, gap analysis, seasonal rotation, budget allocation |
| `career-transition-planner` | Skills gap analysis, reskilling roadmap, networking strategy |
| `social-media-strategist` | Platform selection, posting schedule, engagement strategy, analytics |

#### From `event-planner`
| Agent | What it adds |
|-------|-------------|
| `travel-planner` | Itineraries, booking sequencing, activity research, packing lists, budget |
| `vacation-planner` | Itineraries, booking sequencing, activity research, packing lists |
| `party-planner` | Guest lists, catering, entertainment, timeline, budget, weather contingencies |
| `kids-activity-planner` | Age-appropriate activities, indoor/outdoor options, supply lists, timing |
| `photography-planner` | Shot lists, lighting schedules, location scouting, equipment checklists |

#### From `project-coordinator`
| Agent | What it adds |
|-------|-------------|
| `moving-coordinator` | Timeline, utility transfers, packing schedule, contractor booking |
| `home-renovation-coordinator` | Contractor sequencing, permit timelines, budget tracking, materials |
| `podcast-planner` | Episode scheduling, guest outreach, topic research, production checklists |
| `office-setup-coordinator` | Space planning, equipment procurement, IT setup, lease review |
| `declutter-coordinator` | Room-by-room plan, keep/donate/trash framework, donation logistics |

#### From `decision-analyst`
| Agent | What it adds |
|-------|-------------|
| `product-comparator` | Feature matrices, review aggregation, total cost of ownership |
| `contractor-evaluator` | Bid comparison, reference check questions, scope validation, red flags |
| `vendor-selector` | RFP design, scoring rubric, reference check templates, contract priorities |
| `pricing-model-designer` | Pricing tiers, freemium vs paid, value metric selection, elasticity |
| `partnership-evaluator` | Partner fit scoring, revenue share modeling, integration complexity |

#### From `creative-writer`
| Agent | What it adds |
|-------|-------------|
| `resume-writer` | Achievement framing, ATS optimization, keyword matching, format |
| `pitch-writer` | Hook, problem, solution, traction, ask — investor or client pitch |
| `proposal-writer` | Scope, timeline, pricing, value framing, terms, executive summary |
| `grant-writer` | Funder research, narrative framing, budget justification, outcomes metrics |
| `newsletter-writer` | Subject lines, audience segmentation, CTA design, open rate optimization |
| `speech-writer` | Opening hooks, audience calibration, pacing, callback structure |
| `landing-page-writer` | Hero copy, benefit framing, social proof, CTA hierarchy, SEO |

#### From `communication-drafter`
| Agent | What it adds |
|-------|-------------|
| `cover-letter-writer` | Company research integration, value proposition, tone matching |
| `performance-review-writer` | Achievement framing, growth areas, goal alignment, constructive tone |
| `feedback-giver` | SBI framework, constructive framing, specific examples, action-oriented |
| `apology-drafter` | Accountability framing, impact acknowledgment, remediation plan |
| `complaint-drafter` | Fact documentation, regulation citation, desired outcome, escalation |
| `reference-letter-writer` | Achievement highlighting, character framing, specific examples |
| `cold-email-writer` | Personalization hooks, value-first framing, CTA design, follow-up sequences |

#### From `financial-analyst`
| Agent | What it adds |
|-------|-------------|
| `retirement-planner` | Savings targets, withdrawal strategy, Social Security timing, healthcare |
| `estate-planner` | Asset inventory, beneficiary review, document checklist, trust vs will |
| `subscription-auditor` | Recurring charge detection, usage analysis, cancellation ROI |
| `tax-prep-organizer` | Document checklists, deduction identification, deadline tracking |
| `personal-budget-designer` | Income allocation, envelope method, savings automation |
| `donation-strategist` | Charity evaluation, tax-optimal giving, impact assessment |
| `startup-financial-modeler` | Revenue projections, burn rate, runway calculation, break-even |

#### From `contract-reviewer`
| Agent | What it adds |
|-------|-------------|
| `lease-reviewer` | Rent escalation, maintenance obligations, termination clauses |
| `insurance-reviewer` | Coverage gap analysis, deductible comparison, exclusion flagging |
| `privacy-policy-reviewer` | Data collection scope, third-party sharing, retention periods |

#### From `negotiation-strategist`
| Agent | What it adds |
|-------|-------------|
| `salary-negotiator` | Market data, BATNA preparation, anchor strategy, counter-offer scripts |
| `vendor-negotiator` | Volume discounts, contract terms, SLA requirements, multi-year leverage |

#### From `advisor`
| Agent | What it adds |
|-------|-------------|
| `home-buyer-advisor` | Market analysis, mortgage comparison, inspection checklist |
| `college-application-advisor` | Essay strategy, school matching, timeline, positioning |
| `interview-preparer` | Company research, STAR story prep, question prediction, salary research |

#### From `learning-designer`
| Agent | What it adds |
|-------|-------------|
| `language-learning-planner` | Proficiency assessment, immersion scheduling, grammar sequencing |
| `certification-planner` | Exam requirements, study schedule, resource selection, practice tests |
| `onboarding-designer` | New hire ramp-up plans, mentor pairing, 30/60/90 day milestones |

#### From `online-researcher`
| Agent | What it adds |
|-------|-------------|
| `job-search-researcher` | Company research, role matching, compensation data, interview prep |
| `recipe-finder` | Ingredient matching, dietary filters, technique level, substitutions |
| `reading-list-curator` | Topic scoping, difficulty sequencing, source quality, time estimates |
| `benefits-researcher` | Health insurance options, retirement plans, PTO policies, benchmarking |

#### From `interviewer`
| Agent | What it adds |
|-------|-------------|
| `parent-meeting-preparer` | Agenda framing, concern documentation, collaborative tone |
| `book-club-facilitator` | Discussion questions, theme extraction, passage selection |
| `team-retro-facilitator` | Retro formats (4Ls, sailboat), anonymous input, action items |
| `user-research-interviewer` | Screener design, interview guides, insight synthesis |
| `employee-review-facilitator` | 360 feedback, self-assessment prompts, goal-setting framework |

#### From `test-writer` (cross-domain)
| Agent | What it adds |
|-------|-------------|
| `quiz-maker` | Comprehension questions, difficulty scaling, answer explanations |

#### From `summarizer`
| Agent | What it adds |
|-------|-------------|
| `standup-summarizer` | Blockers, progress, priorities, cross-team dependencies |
| `quarterly-review-preparer` | KPI dashboards, goal progress, financial summary, next-quarter priorities |

#### From `workflow-designer`
| Agent | What it adds |
|-------|-------------|
| `morning-routine-designer` | Time blocking, energy management, habit sequencing, flexibility buffers |
| `content-calendar-designer` | Publishing cadence, topic clustering, platform adaptation |
| `sop-writer` | Step-by-step procedures, role assignments, exception handling |
| `meeting-agenda-designer` | Standing meeting structures, decision frameworks, time allocation |

#### From `brainstormer`
| Agent | What it adds |
|-------|-------------|
| `journal-prompter` | Daily reflection prompts, gratitude framing, emotional processing |

#### From `coach`
| Agent | What it adds |
|-------|-------------|
| `writing-coach` | Craft feedback, voice development, productivity habits, block busting |

### Business Specializations (38)

#### From `business-plan-writer`
| Agent | What it adds |
|-------|-------------|
| `lean-canvas-writer` | One-page Lean Canvas format, hypothesis framing, riskiest assumption |
| `saas-plan-writer` | MRR/ARR modeling, churn assumptions, SaaS-specific metrics |
| `franchise-plan-writer` | Unit economics, territory planning, franchisee requirements |

#### From `brand-designer`
| Agent | What it adds |
|-------|-------------|
| `personal-brand-designer` | LinkedIn presence, thought leadership, content pillars |
| `domain-name-strategist` | Availability checking, TLD selection, trademark conflicts |

#### From `investor-relations-manager`
| Agent | What it adds |
|-------|-------------|
| `seed-fundraiser` | Pre-seed/seed strategy, angel vs VC, SAFE notes, pitch prep |
| `investor-update-writer` | Monthly/quarterly format, key metrics, asks, wins/losses |

#### From `growth-strategist`
| Agent | What it adds |
|-------|-------------|
| `saas-growth-strategist` | Product-led growth, activation funnels, expansion revenue |
| `referral-program-designer` | Incentive structure, tracking mechanics, fraud prevention |
| `local-growth-strategist` | Community partnerships, local SEO, event marketing |

#### From `product-manager`
| Agent | What it adds |
|-------|-------------|
| `mvp-scoper` | Must-have vs nice-to-have, build vs buy, validation metrics |
| `b2b-product-manager` | Enterprise requirements, procurement cycles, compliance needs |

#### From `sales-strategist`
| Agent | What it adds |
|-------|-------------|
| `b2b-sales-strategist` | Enterprise pipeline, multi-stakeholder selling, POC design |
| `cold-outreach-strategist` | Channel selection, personalization at scale, follow-up cadence |
| `upsell-strategist` | Expansion triggers, packaging, cross-sell identification |

#### From `marketing-strategist`
| Agent | What it adds |
|-------|-------------|
| `content-marketing-strategist` | Blog strategy, SEO, thought leadership, distribution |
| `email-marketing-strategist` | List building, segmentation, automation flows, deliverability |
| `local-marketing-strategist` | GMB optimization, local events, community sponsorships |
| `seo-content-strategist` | Keyword research, content clusters, search intent mapping |
| `local-business-marketer` | Google Business Profile, local SEO, review management |

#### From `customer-researcher`
| Agent | What it adds |
|-------|-------------|
| `customer-interview-designer` | Question sequencing, bias avoidance, JTBD framing |
| `survey-designer` | Question types, bias prevention, statistical significance |

#### From `customer-success-manager`
| Agent | What it adds |
|-------|-------------|
| `churn-analyst` | Exit surveys, cohort analysis, leading indicators, win-back campaigns |
| `onboarding-specialist` | First-run experience, activation milestones, handhold sequencing |

#### From `operations-manager`
| Agent | What it adds |
|-------|-------------|
| `supply-chain-manager` | Supplier diversification, lead time optimization, inventory models |
| `inventory-manager` | Reorder points, safety stock, ABC analysis, shrinkage tracking |
| `shipping-optimizer` | Carrier comparison, packaging optimization, zone-based pricing |
| `quality-control-designer` | Inspection checklists, defect categorization, corrective actions |

#### From `bookkeeper`
| Agent | What it adds |
|-------|-------------|
| `cash-flow-forecaster` | 13-week model, AR/AP timing, seasonal adjustment, scenarios |
| `invoice-designer` | Invoice templates, payment terms, late fees, reminder sequences |
| `freelancer-bookkeeper` | Quarterly estimates, 1099 tracking, expense deductions |

#### From `hr-manager`
| Agent | What it adds |
|-------|-------------|
| `job-posting-writer` | Role clarity, culture signaling, compensation transparency, inclusion |
| `contractor-onboarder` | Scope documentation, communication cadence, IP assignment |
| `employee-handbook-writer` | Policy templates, legal compliance, culture documentation |
| `expense-policy-writer` | Category limits, approval workflows, reimbursement timelines |

#### From `legal-advisor`
| Agent | What it adds |
|-------|-------------|
| `entity-formation-advisor` | LLC vs S-Corp vs C-Corp, state selection, operating agreement |
| `trademark-researcher` | USPTO/TESS search, class identification, filing guidance |

#### From various business bases
| Agent | Cloned from | What it adds |
|-------|-------------|-------------|
| `competitive-feature-mapper` | competitor-analyst | Feature-by-feature comparison, pricing tiers, white space |
| `market-sizing-analyst` | business-analyst | TAM/SAM/SOM calculation, bottom-up estimation, assumptions |
| `customer-support-designer` | workflow-designer | Ticket routing, escalation tiers, SLA definitions, FAQ structure |
| `business-insurance-advisor` | risk-assessor | GL, E&O, D&O coverage, policy comparison, claim procedures |
| `compliance-calendar-builder` | compliance-checker | Filing deadlines, renewal dates, regulatory milestones |
| `customer-feedback-analyzer` | data-interpreter | Sentiment clustering, feature request ranking, NPS trends |
| `board-meeting-preparer` | presentation-designer | Board deck structure, financial reporting, key decisions framing |
| `pitch-deck-designer` | presentation-designer | Problem → solution → traction → ask, data visualization |

---

## Phase 1: Research — Finalize Catalog ✅

- [x] **1.1** Audit plan templates to extract all referenced agent types
- [x] **1.2** Research common agent patterns across domains
- [x] **1.3** Map lifecycle coverage and identify gaps
- [x] **1.4** Define the final catalog: **66 base agents**, **174 specialization examples**
- [x] **1.5** Resolve open design questions (read-only, versioning, models, tools, cleanup)

---

## Phase 2: Design — System Prompt Engineering

### Objective
Write detailed system prompts for all 66 base agents.

### System Prompt Template

Every base agent prompt follows this structure:

```
ROLE
  Who you are and what you specialize in.

PROCESS
  Step-by-step methodology you follow.

OUTPUT FORMAT
  Exactly what your output looks like (structure, sections, format).

CONSTRAINTS
  What you must NOT do. Boundaries of your responsibility.

QUALITY STANDARDS
  What "good" looks like for your outputs.

SPECIALIZATION HOOKS
  Markers where domain-specific knowledge gets added when cloned.
  E.g., "When reviewing code, apply general best practices.
  [DOMAIN: Add language-specific patterns here when specializing.]"
```

### Agent Metadata (per agent)
- `description`: One sentence for discovery
- `tags`: 3-5 categorical labels (always includes domain tag: `technical`, `general`, `business`)
- `tools`: Recommended tool set
- `model`: Preferred model (haiku/sonnet/opus)
- `notes`: Guidance for specialization

### Tasks

- [ ] **2.1** Define the system prompt template structure
- [ ] **2.2** Write prompts for Technical — Discovery & Analysis (4 agents)
- [ ] **2.3** Write prompts for Technical — Design & Architecture (3 agents)
- [ ] **2.4** Write prompts for Technical — Implementation (2 agents)
- [ ] **2.5** Write prompts for Technical — Testing & Quality (3 agents)
- [ ] **2.6** Write prompts for Technical — Security & Performance (3 agents)
- [ ] **2.7** Write prompts for Technical — Documentation (2 agents)
- [ ] **2.8** Write prompts for Technical — Infrastructure & Ops (3 agents)
- [ ] **2.9** Write prompts for Technical — Meta (4 agents)
- [ ] **2.10** Write prompts for General — Planning & Strategy (7 agents)
- [ ] **2.11** Write prompts for General — Analysis & Decision-Making (6 agents)
- [ ] **2.12** Write prompts for General — Communication & Writing (7 agents)
- [ ] **2.13** Write prompts for General — Learning & Growth (4 agents)
- [ ] **2.14** Write prompts for General — Finance & Legal (4 agents)
- [ ] **2.15** Write prompts for Business — Startup & Strategy (5 agents)
- [ ] **2.16** Write prompts for Business — Sales & Marketing (4 agents)
- [ ] **2.17** Write prompts for Business — Operations & Finance (5 agents)
- [ ] **2.18** Peer-review all prompts for consistency, gaps, and overlap

---

## Phase 3: Swarm Code Changes — Encourage Specialization

### Objective
Update Swarm's orchestrator and forge to guide users toward cloning from the base catalog.

### Tasks

- [ ] **3.1** Update orchestrator prompt (`src/swarm/cli/main.py`):
  - Reference the base agent catalog and three domains
  - Add "Specialization Ladder" concept: base → domain → project-specific
  - Guide toward cloning before creating from scratch
  - Add examples of good specialization overrides

- [ ] **3.2** Update forge prompt (`src/swarm/forge/prompts.py`):
  - Always show relevant base agents as starting points
  - Structure design flow as "which base agent to clone" first
  - Include specialization examples

- [ ] **3.3** Create `src/swarm/catalog/` module:
  - `base_agents.py` — all 66 base agent definitions as Python data
  - `seed.py` — `seed_base_agents()` function (idempotent)
  - Tags all base agents with `["base", "<domain>"]`
  - Marks base agents with `source="catalog"` to distinguish from user-created
  - Detects parent-update: flags clones when base agent prompt changes

- [ ] **3.4** Add `swarm catalog` CLI command:
  - `swarm catalog` — list all base agents by domain with descriptions
  - `swarm catalog search <query>` — search by name/description/tags
  - `swarm catalog show <name>` — full details + specialization suggestions
  - `swarm catalog seed` — manually trigger base agent seeding

- [ ] **3.5** Auto-seed on first launch:
  - `swarm` and `swarm forge` call `seed_base_agents()` before launching session
  - First launch populates registry; subsequent launches are no-ops

- [ ] **3.6** Update plan templates to use base agent names:
  - `code-review.json` → `code-analyzer`, `code-reviewer`, `technical-writer`
  - `feature-build.json` → `architect`, `implementer`, `test-writer`, `code-reviewer`
  - `security-audit.json` → `security-auditor`, `security-auditor` (clone), `technical-writer`, `code-reviewer`

- [ ] **3.7** Add new plan templates leveraging the expanded catalog:
  - `business-plan.json` — market research → plan writing → financial modeling → review
  - `hiring-pipeline.json` — job posting → sourcing → interview design → evaluation
  - `product-launch.json` — research → MVP scope → implement → market → launch

---

## Phase 4: Testing & Validation

### Tasks

- [ ] **4.1** Write tests for `seed_base_agents()` — idempotency, correct metadata, all 66 agents
- [ ] **4.2** Write tests for parent-update flagging
- [ ] **4.3** Write tests for `swarm catalog` CLI commands
- [ ] **4.4** Test plan template instantiation — verify templates resolve to base agents
- [ ] **4.5** Test specialization workflow — clone a base agent, add domain knowledge, verify
- [ ] **4.6** Run existing test suite (753 tests) to verify no regressions
- [ ] **4.7** Integration test: full orchestrator flow (describe goal → suggests cloning → builds plan)

---

## Phase 5: Documentation

### Tasks

- [ ] **5.1** Update `design.md` with base agent catalog section (66 agents, 3 domains)
- [ ] **5.2** Update `README.md` with getting-started guidance and catalog overview
- [ ] **5.3** Update `CLAUDE.md` with new modules and conventions
- [ ] **5.4** Write "How to Specialize an Agent" guide with examples from each domain

---

## Implementation Order

```
Phase 1 (Research)          ✅ COMPLETE
  ↓
Phase 2 (System Prompts)    ← Next: write 66 prompts
  ↓
Phase 3 (Code Changes)      ← Depends on Phase 2 (needs prompts to seed)
  ↓                            3.1-3.2 can start in parallel with Phase 2
Phase 4 (Testing)           ← Depends on Phase 3
  ↓
Phase 5 (Documentation)     ← Can start in parallel with Phase 4
```

### Estimated Scope
- **66 base agent definitions** with detailed system prompts (~300-500 words each)
- **174 specialization examples** documented for reference
- **~300 lines** of orchestrator/forge prompt updates
- **~800 lines** of new Python code (catalog module, seed function, CLI commands, parent-update flagging)
- **~200 lines** of test code
- **6 plan templates** (3 updated + 3 new)
- **~200 lines** of documentation updates
