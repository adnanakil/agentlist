# HAL Eval Report

432 runs — 54 scenarios x 8 models. Judge: fixed model, blind to candidate identity. Handled-rate excludes na (judge/harness failures).

**Round 2 (2026-07-13).** gpt-5.6 is a three-tier family — sol (flagship, $5/$30), terra (mid, $2.50/$15), luna (economy, $1/$6) — so v1's headline compared last-gen's flagship (gpt-5.4) against this gen's economy tier; this round adds terra, sol, and gemini-3.5-flash (all three providers funded). Changes vs v1: system-prompt clock now frozen per scenario (8 clock-invalidated scenarios re-run on the original five models — those rows mix harness versions for the other 46), OpenAI/Gemini cached-token usage normalized to disjoint buckets (v1 overstated OpenAI costs on cache-heavy turns), and every grade below is from one consistent fixture-aware judge pass.

## Overall

| Model | Handled | Partial | Failed | na | Handled-rate | Asserts | Mean $/turn | Median $/turn | Mean latency |
|---|---|---|---|---|---|---|---|---|---|
| gpt-5.4-mini | 24 | 13 | 15 | 2 | 46.2% | 47/54 | $0.0285 | $0.0139 | 42.8s |
| gpt-5.4 | 23 | 14 | 16 | 1 | 43.4% | 46/54 | $0.0700 | $0.0555 | 33.6s |
| gpt-5.6-sol | 23 | 12 | 18 | 1 | 43.4% | 48/54 | $0.1113 | $0.0965 | 18.6s |
| gpt-5.6-luna | 22 | 11 | 20 | 1 | 41.5% | 45/54 | $0.0216 | $0.0185 | 14.3s |
| gpt-5.6-terra | 19 | 14 | 20 | 1 | 35.8% | 44/54 | $0.0495 | $0.0463 | 9.2s |
| gemini-3.5-flash | 19 | 18 | 17 | 0 | 35.2% | 44/54 | $0.0884 | $0.0819 | 22.4s |
| claude-sonnet-5 | 18 | 12 | 23 | 1 | 34.0% | 43/54 | $0.0558 | $0.0319 | 9.0s |
| claude-haiku-4-5 | 15 | 12 | 26 | 1 | 28.3% | 42/54 | $0.0123 | $0.0054 | 3.8s |

## Handled-rate by category

| Category | gpt-5.4-mini | gpt-5.4 | gpt-5.6-sol | gpt-5.6-luna | gpt-5.6-terra | gemini-3.5-flash | claude-sonnet-5 | claude-haiku-4-5 |
|---|---|---|---|---|---|---|---|---|
| baby-logging | 25.0% | 0.0% | 25.0% | 37.5% | 25.0% | 25.0% | 25.0% | 25.0% |
| fact-check-links | 80.0% | 80.0% | 100.0% | 60.0% | 60.0% | 16.7% | 80.0% | 40.0% |
| group-restraint | 66.7% | 50.0% | 50.0% | 33.3% | 16.7% | 16.7% | 16.7% | 16.7% |
| memory-recall | 16.7% | 33.3% | 0.0% | 16.7% | 0.0% | 33.3% | 0.0% | 0.0% |
| multi-tool-errands | 14.3% | 50.0% | 37.5% | 25.0% | 50.0% | 12.5% | 25.0% | 25.0% |
| proactive-judgment | 75.0% | 75.0% | 75.0% | 75.0% | 62.5% | 75.0% | 62.5% | 62.5% |
| reminders-time | 50.0% | 25.0% | 25.0% | 50.0% | 37.5% | 50.0% | 37.5% | 25.0% |
| tone-format | 50.0% | 50.0% | 50.0% | 25.0% | 25.0% | 50.0% | 25.0% | 25.0% |

## Paired comparison vs gpt-5.6-luna

Discordant scenarios only (one model handled it, the other didn't); p = two-sided exact binomial. Small n means most gaps here are within noise — treat p < 0.05 as real signal.

| Model | Wins | Losses | p |
|---|---|---|---|
| claude-haiku-4-5 | 1 | 8 | 0.039 |
| claude-sonnet-5 | 5 | 9 | 0.424 |
| gemini-3.5-flash | 7 | 10 | 0.629 |
| gpt-5.4 | 6 | 5 | 1.000 |
| gpt-5.4-mini | 6 | 3 | 0.508 |
| gpt-5.6-sol | 7 | 6 | 1.000 |
| gpt-5.6-terra | 2 | 5 | 0.453 |

## Projected monthly cost

Prod volume: **34 turns/day** (hal_turns, trailing 14 days). Projection = mean eval cost/turn x volume x 30. Eval turns skew heavier than prod (fixtures force tool loops), so treat these as an upper bound for ranking, not a bill forecast.

| Model | Mean $/turn | $/day | $/month |
|---|---|---|---|
| gpt-5.4-mini | $0.0285 | $0.96 | $28.94 |
| gpt-5.4 | $0.0700 | $2.37 | $71.16 |
| gpt-5.6-sol | $0.1113 | $3.77 | $113.22 |
| gpt-5.6-luna | $0.0216 | $0.73 | $22.01 |
| gpt-5.6-terra | $0.0495 | $1.68 | $50.35 |
| gemini-3.5-flash | $0.0884 | $3.00 | $89.86 |
| claude-sonnet-5 | $0.0558 | $1.89 | $56.77 |
| claude-haiku-4-5 | $0.0123 | $0.42 | $12.54 |

## Recommendation

**gpt-5.4-mini** is both the best-scoring (46.2%) and the cheapest eligible model.

## Failures (partial + failed)

### gpt-5.4-mini
- `baby-digest-slash` [baby-logging] failed (bad_judgment): HAL stayed silent on /baby-digest despite invoking the skill and stats tools, when a digest reply was explicitly required.
- `baby-log-ambiguous-505` [baby-logging] failed (bad_judgment): HAL guess-logged the ambiguous '505' as a feed (multiple times, with an undo/re-log) and replied 'Logged' instead of asking a clarifying question or confirming the interpretation first — exactly the failure being tested.
- `baby-log-no-phantom-claim` [baby-logging] failed (hallucination): Feed was logged via the tool but at 10:14 AM instead of ~12:28 PM, and the reply claims a 'bottle prep reminder set' with no such tool call in the trace — fabricated success.
- `errand-booking-handoff` [multi-tool-errands] partial (bad_judgment): Gave the direct booking link and a helpful handoff, but omitted the expected offer to set a reminder/calendar note so the booking doesn't slip.
- `errand-fuzzy-place-reference` [multi-tool-errands] partial (bad_judgment): It usefully surfaced Brass Monkey and Highline Ballroom as actual World Cup venues, but fixated on the 7th Ave 'Cafeteria' restaurant correction instead of interpreting the reference as the food hall (Chelsea Market/Gansevoort) near 11th and answering that those don't show matches.
- `errand-lunch-pivot` [multi-tool-errands] failed (bad_judgment): After extensive tool calls returning lunch options, the reply punts by asking for day and party size instead of giving picks — the exact tested failure.
- `errand-open-day-plan` [multi-tool-errands] partial (missed_tool): Gave a nap/feed-rhythm plan but never pulled weather (missed the UV 11-2 shade guidance) or calendar, and deferred exact times instead of anchoring the ~9-9:30 nap concretely.
- `errand-sports-today` [multi-tool-errands] failed (bad_judgment): The sports tool explicitly said today (Jul 8) has the Argentina–Netherlands semifinal at 9 PM ET, but the reply said there's no game today — the opposite of the ground truth.
- `errand-weather-tool-down` [multi-tool-errands] partial (bad_judgment): Fell back to search correctly and gave a real recommendation without punting, but 'go this morning if you can head out soon' contradicts the data (showers until ~10 AM); expected late-morning or afternoon.
- `factcheck-captcha-fallback` [fact-check-links] failed (bad_judgment): Despite web_search returning the full answer (NY 2023 law, new construction only, 2026 phase-in, existing homes unaffected), the reply ignored it, misstated the captcha as a broken/expired link, and punted to the user — exactly the failure mode the playbook forbids.
- `group-capture-ambient-answer` [group-restraint] partial (missed_tool): Correctly interpreted '310' as 3:10 PM and confirmed briefly, but no memory/reminder tool call in the trace to actually persist it as required.
- `group-humans-converging` [group-restraint] failed (bad_judgment): HAL spoke when silence was required, injecting an unneeded confirmation into a human-only convergence.
- `heartbeat-delivery-landed` [proactive-judgment] failed (bad_judgment): Stayed silent when a package-delivered heads-up was required to be surfaced.
- `heartbeat-rain-window-alert` [proactive-judgment] failed (bad_judgment): Stayed silent when a rain alert was required, and never even checked weather via tools.
- `memory-date-resolution` [memory-recall] failed (bad_judgment): The projector is due today (Wednesday July 8), but the reply claims the date has 'already passed' — wrong resolution against the current date, which the rubric says fails.
- `memory-recall-list` [memory-recall] failed (infra_error): Expected recall of all four items, but every tool call returned empty and the reply admitted nothing was found — the list was not recalled at all.
- `memory-recall-rules` [memory-recall] partial (other): Accurately recalled the stroller nap (~15 min) and tummy time (~30 min after feeds) rules without inventing anything, but omitted the seeded feeding schedule (~every 2.5-3h from ~6:30 AM).
- `memory-store-standing-rule` [memory-recall] partial (bad_judgment): A durable write for the tummy-time routine appears in the trace, but the reply asks a possibly unnecessary question about the baby's name instead of cleanly confirming the standing rule.
- `memory-update-contradiction` [memory-recall] partial (bad_judgment): It persisted the new preference and confirmed briefly, but used profile append instead of the expected memory update, leaving the old 'blue' fact potentially uncorrected and failing the hard assertion.
- `reminder-actually-created` [reminders-time] failed (bad_judgment): Reminder was set for the wrong date (Jul 14 instead of Jul 8 per the hard assertion) and the reply dropped the 8-10 guest-count answer entirely, calling it 'unclear' — the rubric explicitly marks dropping that answer as a fail.
- `tone-group-brevity` [tone-format] partial (bad_judgment): Core answer is correct and concise (walk fine, avoid 11-2 UV), but tacks on an unnecessary off-topic question about setting up a baby tracker in a group chat.
- `tone-no-filler-confirm` [tone-format] failed (bad_judgment): Instead of a brief confirmation, the reply asks an unnecessary question and adds an emoji, contradicting the expected no-question, 1-2 line acknowledgment despite the log tool call being made.
- `baby-log-correction` [baby-logging] partial (bad_judgment): Trace shows undo+relog at 9:30 as expected, but the undo targeted kind 'note' rather than the wake entry, and the reply doesn't confirm the corrected 9:30 time as required.
- `baby-log-feed-terse` [baby-logging] partial (hallucination): Feed was logged via the tool and briefly confirmed, but the reply fabricates a 'bottle prep reminder set' not supported by the trace (auto_feed_prep was false) and appends a stray URL.
- `baby-log-multi-event` [baby-logging] failed (bad_judgment): Only one event was logged (and with wrong AM time instead of 6:10 PM), bedtime was never logged, and instead of acknowledging both events it asked an unnecessary question — 'slept at 7:10' evening context was misread as a morning nap.
- `countdown-not-started-yet` [reminders-time] failed (bad_judgment): Instead of computing the ~54-minute countdown, HAL punted with a clarifying question and gave no time math at all, ignoring the ask.
- `leaveby-travel-math` [reminders-time] partial (bad_judgment): Correctly reported the 40/55-min travel figures but failed to compute the expected ~3:45-4:00 PM leave-by for the 5 PM kickoff, instead asking an unnecessary question for info it should have used.
- `reminder-relative-45min` [reminders-time] partial (bad_judgment): The final reminder at 4:55 PM was created and confirmed concisely, but the trace shows a duplicate reminder was created on Jul 8 and never cancelled, leaving a stray wrong-day reminder.

### gpt-5.4
- `baby-digest-slash` [baby-logging] failed (bad_judgment): HAL stayed silent on a /baby-digest slash command that must always produce a digest, despite having called the stats tools.
- `baby-log-ambiguous-505` [baby-logging] failed (bad_judgment): HAL guess-logged a 5:05 PM feed without confirming the ambiguous '505' first, which is exactly the failure this scenario tests; the after-the-fact 'say the word' doesn't substitute for confirming before logging.
- `baby-log-daytime-not-bedtime` [baby-logging] partial (bad_judgment): Correctly logged nap_start (not bedtime) and confirmed briefly, but logged 10:12 AM instead of the stated 11 AM time.
- `baby-log-no-phantom-claim` [baby-logging] partial (hallucination): Feed was logged via the baby tool as required, but the reply claims a bottle prep reminder was set for 12:58 PM with no tool call in the trace to support it.
- `baby-log-wake-confirm` [baby-logging] partial (bad_judgment): The reply stays on-topic and implies the wake was noted, but it never explicitly confirms the log or states the time/catnap length, and the tool logged 10:13 AM rather than the expected 11:30 AM.
- `errand-booking-handoff` [multi-tool-errands] partial (bad_judgment): Provided the direct booking link and a helpful next step, but skipped the expected offer to set a reminder/calendar note so the booking doesn't slip.
- `errand-fuzzy-place-reference` [multi-tool-errands] partial (bad_judgment): Correctly interpreted the food-hall reading and said no matches there, but withheld the confirmed nearby venues (Brass Monkey, Highline Ballroom Bar) it already had in evidence, asking permission instead of offering them.
- `errand-open-day-plan` [multi-tool-errands] partial (bad_judgment): Weather-aware, concrete plan with honest hedging, but it failed to thread Bazzy's nap/feed rhythm (the core expectation), instead punting with a request for the log, and its 10:45-12 outdoor block partly overlaps the UV peak.
- `errand-sports-today` [multi-tool-errands] failed (bad_judgment): The sports tool clearly said today (Jul 8) has Argentina vs Netherlands at 9 PM ET, but the reply denied any match today, contradicting the ground-truth data.
- `factcheck-captcha-fallback` [fact-check-links] failed (missed_tool): Stopped at the captcha and asked the user to describe the video without trying web_search, exactly the failure mode the playbook rule prohibits.
- `group-direct-ask-must-answer` [group-restraint] failed (missed_tool): Deflected the core ask by requesting location instead of calling places and providing the fixture's pharmacy options — deflection is the explicitly tested failure, despite otherwise helpful interim advice.
- `group-humans-converging` [group-restraint] failed (bad_judgment): HAL replied when silence was required; humans had already converged and HAL wasn't addressed.
- `group-respect-stfu` [group-restraint] failed (bad_judgment): HAL sent a reply ('👍') when silence was explicitly required after the user's mute request.
- `heartbeat-rain-window-alert` [proactive-judgment] failed (bad_judgment): Stayed silent when a rain alert was required, and never checked weather.
- `heartbeat-time-sanity` [proactive-judgment] partial (hallucination): Time framing is correctly pre-event and internally consistent, but the transit frequency and weather details are asserted with no tool calls to support them.
- `memory-date-resolution` [memory-recall] failed (other): The reply never surfaces the stored arrival date or connects it to today (Wednesday July 8) — it claims no info found and asks the user for tracking, missing the ask entirely.
- `memory-recall-rules` [memory-recall] partial (other): Accurately recalled stroller nap timing, nap-aware planning, and tummy time without inventing rules, but omitted the seeded feed cadence rule (~every 2.5-3h from ~6:30 AM).
- `memory-store-standing-rule` [memory-recall] partial (bad_judgment): A durable configure call was made persisting the routine, but the reply doesn't cleanly confirm the standing behavior — it hinges completion on getting the baby's name, adding an extra step not clearly required and leaving the user unsure the rule is actually in place.
- `memory-update-contradiction` [memory-recall] partial (missed_tool): A persistent write did occur (profile set to green) with a brief confirmation, but the expected memory tool was not used and the change from blue wasn't acknowledged.
- `reminder-actually-created` [reminders-time] failed (bad_judgment): Reminder was created but for the wrong date (7/14 vs expected 7/8, six days off), and the '8-10' answer was misinterpreted as a work-hours routine rather than the guest count, mishandling the second part of the ask.
- `stale-price-caveat` [reminders-time] failed (hallucination): Ignored the fixtured TicketIQ data ($1,820 as of June 6) entirely, falsely claimed pricing hasn't been released, and substituted historical/speculative figures — contradicting the ground truth it had.
- `tone-group-brevity` [tone-format] failed (verbosity): The rubric explicitly says essay-length fails on format even if accurate; the reply is multi-paragraph with an unnecessary setup question instead of ≤3 short lines.
- `tone-no-filler-confirm` [tone-format] failed (bad_judgment): Instead of a brief confirmation, the reply asks for the baby's name and defers the log, contradicting the tool trace showing the log was already attempted and violating the no-questions expectation.
- `baby-log-correction` [baby-logging] partial (bad_judgment): Logged a 9:30 wake with a correction note but the trace shows no undo/removal of the original 8:50 entry, likely leaving two wake records despite confirming 'corrected'.
- `baby-log-feed-terse` [baby-logging] failed (hallucination): The feed was logged via the tool, but the reply fabricates a 'bottle-prep reminder set for 5:00' that no tool call supports, and appends a stray URL instead of a clean confirmation.
- `baby-log-multi-event` [baby-logging] failed (bad_judgment): Only logged one event with wrong AM time, no bedtime log, asked unnecessary questions, and addressed the wrong person instead of acknowledging both events to Joyce.
- `countdown-not-started-yet` [reminders-time] partial (bad_judgment): Avoided the 'already started' failure and didn't fabricate, but never gave the ~54-minute countdown, deflecting with a clarifying question instead of answering.
- `leaveby-travel-math` [reminders-time] partial (bad_judgment): Correctly used the 40/55-min travel figures and gave a sensible buffer, but assumed a 7pm start instead of the 5:00 PM kickoff, so the leave-by times (5:00/5:15) don't match the expected ~3:45-4:00 PM.
- `reminder-relative-45min` [reminders-time] failed (bad_judgment): Created duplicate reminders and confirmed 4:48 PM instead of the expected 4:55 PM today, with the second reminder set five days later.
- `reminder-weekday-math` [reminders-time] partial (other): Reminder set for the correct date (July 16, 1:30 PM) but the confirmation omits the explicit date, which the expected behavior requires to verify resolution.

### gpt-5.6-sol
- `baby-digest-slash` [baby-logging] failed (bad_judgment): HAL stayed silent on /baby-digest despite the situation explicitly requiring a reply with matching counts.
- `baby-log-correction` [baby-logging] partial (missed_tool): HAL logged a new 9:30 wake with a correction note but never undid/removed the original 8:50 entry, so the trace likely leaves two wake records — the exact duplicate the expected behavior forbids.
- `baby-log-daytime-not-bedtime` [baby-logging] partial (bad_judgment): Correctly logged nap_start (not bedtime) and confirmed briefly, but the logged time is 15:58-04:00 (~4 PM local), not the ~11 AM the situation specifies, so the time detail is wrong.
- `baby-log-feed-terse` [baby-logging] partial (hallucination): Feed log correctly confirmed, but claimed a 5:00 PM bottle prep reminder was set with no supporting tool call, and appended an unexplained link.
- `baby-log-multi-event` [baby-logging] failed (bad_judgment): Logged only one event with the wrong time (6:10 AM instead of PM), never logged the bedtime, misread evening times as morning, and asked an unnecessary question instead of confirming both events to Joyce.
- `baby-log-no-phantom-claim` [baby-logging] failed (hallucination): The baby tool was called but logged the feed at 3:58 PM instead of ~12:28 PM, and the reply fabricates a 'bottle-prep reminder set for 6:43 PM' with no supporting tool call in the trace.
- `countdown-not-started-yet` [reminders-time] failed (bad_judgment): HAL never provided the ~54-minute countdown, instead asking an unnecessary clarifying question and ignoring the time math the user needed.
- `errand-booking-handoff` [multi-tool-errands] partial (bad_judgment): Provided the direct booking link and slot details but omitted the expected offer to set a reminder/calendar note per the playbook.
- `errand-fuzzy-place-reference` [multi-tool-errands] partial (bad_judgment): Correctly interpreted the fuzzy reference as an 11th Ave food hall and said no screenings found, but ignored the evidence pointing to Chelsea Market/Gansevoort and skipped offering the verified nearby World Cup venues (Brass Monkey, Highline Ballroom Bar), instead asking a follow-up question.
- `errand-lunch-pivot` [multi-tool-errands] failed (bad_judgment): Despite gathering all lunch data via tools, HAL committed the exact tested failure by asking for 'one more detail' instead of returning lunch picks.
- `errand-open-day-plan` [multi-tool-errands] failed (bad_judgment): Reply plans a generic late-afternoon outing and claims nothing is logged for Bazzy, entirely missing the expected nap/feed threading (~9-9:30 nap off the 6:40 wake, 2.5-3h feeds) and the 11-2 UV shade window — the standout feature the turn was testing.
- `errand-weather-tool-down` [multi-tool-errands] partial (bad_judgment): Correctly fell back to web_search and gave a concrete late-morning recommendation, but tacked on an unnecessary question about the baby's name that wasn't part of the ask.
- `group-capture-ambient-answer` [group-restraint] partial (missed_tool): Correctly interpreted '310' as 3:10 and confirmed briefly, but made no memory/reminder tool call to persist it as required.
- `group-direct-ask-must-answer` [group-restraint] failed (missed_tool): Deflected by asking for a location instead of calling places and giving the fixture's pharmacy options — exactly the tested failure mode.
- `group-humans-converging` [group-restraint] failed (bad_judgment): HAL replied when silence was required, inserting itself into a human conversation where it wasn't addressed.
- `heartbeat-rain-window-alert` [proactive-judgment] failed (bad_judgment): Stayed silent when a concise rain alert was required, and made no tool calls to check the forecast.
- `heartbeat-time-sanity` [proactive-judgment] partial (hallucination): Time framing is correctly pre-event (starts at 5 PM, leave now), but the NJ Transit 'every 10 minutes' claim is fabricated with no tool call to support it.
- `leaveby-travel-math` [reminders-time] failed (missed_tool): Instead of using the travel_time figures to compute a leave-by time (~3:45-4:00 PM), it never called travel_time and asked the user for event time and mode, ignoring the ask.
- `memory-date-resolution` [memory-recall] failed (other): The reply never surfaced the stored delivery date or connected it to today (Wednesday July 8); it claimed no info was found and pushed the work back to the user.
- `memory-recall-list` [memory-recall] failed (infra_error): None of the four stored items were recalled; all six retrieval attempts returned empty, and while HAL honestly admitted failure rather than fabricating, the required list was not produced.
- `memory-recall-rules` [memory-recall] failed (hallucination): Only the ~15-min stroller nap rule matches the seeded rules; it omits tummy time ~30 min after feeds and feeds every 2.5-3h from 6:30 AM, and invents multiple unseeded rules (live tracking, awake-for-activities, flag tensions).
- `memory-recall-simple` [memory-recall] failed (bad_judgment): HAL claimed not to know the stored fact, which the expected behavior explicitly marks as a failure.
- `memory-store-standing-rule` [memory-recall] partial (bad_judgment): The standing rule was persisted via the baby configure call and confirmed, but the reply tacks on an unnecessary question about the baby's name instead of a clean one-line confirmation.
- `memory-update-contradiction` [memory-recall] partial (bad_judgment): A persistent write did occur and the reply confirmed green, but it appended to the profile instead of updating/removing the stored blue fact via the memory tool, leaving a contradiction.
- `reminder-actually-created` [reminders-time] partial (bad_judgment): Reminder was actually created via tool and both answers acknowledged, but the trace shows two reminders created (July 8 and July 14) with the erroneous first one never cancelled, leaving a stray duplicate.
- `reminder-no-time-given` [reminders-time] partial (bad_judgment): Reply correctly states an inferred 9 AM time, but the trace shows two reminders created on different dates (Jul 9 and Jul 14), leaving a duplicate/wrong-date reminder persisted.
- `reminder-relative-45min` [reminders-time] failed (bad_judgment): Created duplicate reminders and confirmed the wrong time (4:57 PM, on a different date) instead of the expected 4:55 PM today.
- `timer-sous-vide` [reminders-time] failed (bad_judgment): Answered 1 hour 13 minutes (computed from 4:12) instead of the correct 35 minutes remaining from the current time of 4:50 PM, an answer inconsistent with the frozen clock.
- `tone-group-brevity` [tone-format] failed (missed_tool): Ignored the ask — never called get_weather, gave no walk/UV answer, and instead asked unnecessary setup questions in the group.
- `tone-no-filler-confirm` [tone-format] failed (bad_judgment): Instead of a brief confirmation of the logged tummy time, the reply asks a question and implies the log hasn't happened yet, contradicting the tool trace.

### gpt-5.6-luna
- `baby-digest-slash` [baby-logging] failed (bad_judgment): The /baby-digest command requires a reply but HAL stayed silent despite invoking the skill and stats tools.
- `baby-log-ambiguous-505` [baby-logging] partial (bad_judgment): HAL correctly avoided guess-logging and asked one clarifying question, but its offered interpretations (bedtime/reminder) don't match the likely feed context (5:05 PM feed vs. correction to the 4:40 feed), so the clarification may not resolve the ambiguity.
- `baby-log-no-phantom-claim` [baby-logging] partial (hallucination): Feed was logged via the baby tool as required, but the reply also claims a bottle prep reminder was set for 12:55 PM with no supporting tool call (auto_feed_prep was false), a fabricated action.
- `errand-booking-handoff` [multi-tool-errands] partial (bad_judgment): Provided the booking link and 8:00 PM slot handoff, but omitted the offer to set a reminder/calendar note required by the playbook, and altered the link's date parameter from the one the tool returned.
- `errand-fuzzy-place-reference` [multi-tool-errands] failed (bad_judgment): Despite having full evidence (Chelsea Market/Gansevoort near 11th, no TVs, and actual World Cup venues like Brass Monkey), the reply asks for clarification and provides nothing.
- `errand-open-day-plan` [multi-tool-errands] failed (infra_error): No day plan was delivered — the baby tool calls returned empty/garbled data and the reply punted to clarifying questions instead of providing the nap-aware itinerary that was the core ask.
- `errand-sports-today` [multi-tool-errands] failed (hallucination): Reply says no match today, directly contradicting the sports tool data showing Argentina vs Netherlands semifinal tonight at 9 PM ET at MetLife, and it fell into the search loop instead of answering from the tool.
- `errand-typo-train` [multi-tool-errands] failed (missed_tool): Instead of inferring 'train' and answering with the transit time, it asked clarifying questions and never called travel_time — exactly the failure mode the situation says to avoid.
- `errand-weather-tool-down` [multi-tool-errands] failed (bad_judgment): Despite having web_search results (showers ending by 10 AM), the reply exposed the tool failure and punted with 'do a quick door check' — the exact prohibited behavior.
- `factcheck-captcha-fallback` [fact-check-links] failed (bad_judgment): Despite search results containing the full answer (new-construction-only, 2026 phase-in, existing homes unaffected), the reply punted to the user asking for the link/description and misattributed the block to a broken/removed link rather than a captcha.
- `factcheck-no-fabrication` [fact-check-links] partial (hallucination): Delivers real value from title + search and discloses it couldn't get the transcript, but leads with a 'Mostly true — but oversimplified' verdict and characterizes the video's 'hype,' claiming more certainty about the video's actual content than the title/description support.
- `group-capture-ambient-answer` [group-restraint] partial (missed_tool): Correctly interpreted '310' as 3:10 PM and confirmed briefly, but no memory/reminder tool call appears in the trace, so the info wasn't persisted as required.
- `group-direct-ask-must-answer` [group-restraint] failed (missed_tool): Deflected by asking for the neighborhood instead of calling places and giving the fixture's pharmacy options — deflecting is the exact tested failure.
- `group-humans-converging` [group-restraint] failed (bad_judgment): HAL spoke when silence was required, adding a redundant confirmation to a human-converged plan.
- `group-respect-stfu` [group-restraint] failed (bad_judgment): HAL replied to banter despite an explicit mute; silence was required, and the erratic mute/unmute tool churn shows it also undermined the mute state.
- `heartbeat-rain-window-alert` [proactive-judgment] failed (bad_judgment): Stayed silent when a concise rain alert was required, and never called any tool to check the forecast.
- `heartbeat-time-sanity` [proactive-judgment] partial (hallucination): Time framing is correctly pre-event ('heading out now' before 5 PM kickoff), but the NJ Transit service frequency claim is unsupported by any tool call in the trace.
- `memory-date-resolution` [memory-recall] failed (bad_judgment): The reply never surfaces the stored arrival date or connects it to today (Wednesday July 8); it claims it couldn't find the info and punts back to the user instead of answering.
- `memory-recall-list` [memory-recall] failed (infra_error): None of the four items were recalled; the tools returned empty results and the reply, while honest and non-fabricating, did not meet the required recall of the list.
- `memory-recall-rules` [memory-recall] failed (infra_error): The seeded rules were never surfaced — all recall/profile/baby lookups came back empty and the reply asked the user to resend instead of recalling the rules; honest, but the core ask (accurate recall) was not delivered.
- `memory-store-standing-rule` [memory-recall] partial (bad_judgment): The rule was durably persisted via the baby configure call, but the reply adds an unnecessary question about the baby's name instead of simply confirming the standing behavior.
- `memory-update-contradiction` [memory-recall] partial (missed_tool): A write occurred and the change was confirmed, but it appended via profile instead of updating memory, leaving the contradicting 'blue' fact in place and failing the expected memory-tool assertion.
- `reminder-actually-created` [reminders-time] failed (bad_judgment): Reminder was created for the wrong date (July 14 vs expected July 8), and the 8-10 guest count answer was misread as a time range, prompting an unnecessary question instead of an acknowledgment.
- `tone-group-brevity` [tone-format] failed (missed_tool): Never called get_weather and asked unnecessary questions instead of giving the walk/UV answer the group needed.
- `tone-no-error-leak` [tone-format] partial (missed_tool): No raw errors leaked, but HAL never attempted the lookup — it asked a clarifying question instead of trying the tools and delivering the graceful can't-get-data message expected.
- `tone-no-filler-confirm` [tone-format] failed (bad_judgment): Instead of a brief log confirmation, HAL asked an unnecessary question and didn't acknowledge the tummy time as logged despite calling the tool.
- `baby-log-feed-terse` [baby-logging] partial (hallucination): Feed was logged and confirmed briefly, but the reply claims a 5:00 PM bottle prep reminder was set, which the tool trace does not support, and appends a stray link.
- `baby-log-multi-event` [baby-logging] failed (bad_judgment): Logged the feed at 6:10 AM instead of PM, treated bedtime as a nap, never logged the second event, and stalled by asking for the baby's name instead of acknowledging both events.
- `countdown-not-started-yet` [reminders-time] partial (bad_judgment): Avoided the 'already started' failure and asked a clarifying question, but never delivered the ~54-minute countdown the situation required despite calling the time tool.
- `leaveby-travel-math` [reminders-time] failed (missed_tool): Never called travel_time and asked clarifying questions instead of computing the leave-by time (~3:45-4:00 PM) as expected.
- `reminder-relative-45min` [reminders-time] failed (bad_judgment): Created a duplicate second reminder with a wrong date/time (Jul 13 4:43 PM) and confirmed the wrong time instead of the correct 4:55 PM today.

### gpt-5.6-terra
- `baby-digest-slash` [baby-logging] failed (bad_judgment): HAL stayed silent on /baby-digest despite tool calls returning data; the command must always produce a digest reply.
- `baby-log-ambiguous-505` [baby-logging] failed (bad_judgment): HAL guess-logged a 5:05 PM feed without confirming the ambiguous '505' — exactly the tested failure — and its reply ('I'll log once he's had it') even contradicts the tool trace showing it already logged.
- `baby-log-correction` [baby-logging] partial (bad_judgment): It logged a 9:30 wake with a correction note but the trace shows no undo/removal of the 8:50 entry, risking duplicate wakes, and the reply never confirms the corrected 9:30 time.
- `baby-log-feed-terse` [baby-logging] partial (hallucination): Feed log correctly confirmed per tool trace, but the claimed 5:00 bottle-prep reminder is unsupported by the trace (auto_feed_prep was false), and an odd URL was appended.
- `baby-log-multi-event` [baby-logging] failed (bad_judgment): Only one event logged (and at 6:10 AM instead of 6:10 PM), bedtime never logged, no acknowledgment to Joyce — instead asked an unnecessary question and treated 'slept' as a nap.
- `baby-log-no-phantom-claim` [baby-logging] partial (hallucination): Feed was logged via the baby tool, but the reply claims a bottle-prep reminder was set with no such tool call in the trace, and the logged time (3:58 PM) doesn't match the expected ~12:28 PM.
- `countdown-not-started-yet` [reminders-time] partial (bad_judgment): Avoided the prod failure (no 'already started' claim) and correctly read the current time, but never gave the ~54-minute countdown, deflecting with a clarifying question instead of answering the ask.
- `errand-booking-handoff` [multi-tool-errands] partial (bad_judgment): Provided the direct booking link and slot details but omitted the offer to set a reminder/calendar note required by the playbook.
- `errand-fuzzy-place-reference` [multi-tool-errands] failed (bad_judgment): The reply fixated on the 7th Ave 'Cafeteria' restaurant instead of interpreting the reference as the food halls near 11th Ave (Chelsea Market/Gansevoort), which the expected behavior explicitly calls a failure, despite mentioning Brass Monkey.
- `errand-open-day-plan` [multi-tool-errands] failed (hallucination): Reply asserts a nonsensical 11:46 AM 'bedtime' unsupported by the trace, ignores the weather/UV data and places results entirely, and delivers a confusing morning-only schedule instead of the expected nap-and-UV-aware day plan.
- `errand-weather-tool-down` [multi-tool-errands] failed (missed_tool): Never fell back to web_search after the weather tool errored, punted with a generic recommendation and asked unnecessary questions instead of giving the real forecast-based answer.
- `factcheck-captcha-fallback` [fact-check-links] failed (missed_tool): Punted to the user after the captcha without trying web_search, violating the playbook rule and missing the fact-check the search would have enabled.
- `factcheck-no-fabrication` [fact-check-links] partial (bad_judgment): Delivers accurate value from the search evidence without fabricating transcript details, but never discloses it couldn't pull the actual video, and critiques the video's claim ('a little ahead of itself') as if it evaluated its content.
- `group-capture-ambient-answer` [group-restraint] partial (missed_tool): Correctly interpreted '310' as 3:10 PM and confirmed briefly, but no memory/reminder tool call in the trace to persist the answer as required.
- `group-direct-ask-must-answer` [group-restraint] failed (missed_tool): Deflected the urgent ask by requesting location instead of calling places and giving the fixtured pharmacy options — exactly the tested failure mode.
- `group-humans-converging` [group-restraint] failed (bad_judgment): Spoke when silence was required, echoing a recap nobody asked for after humans converged themselves.
- `group-privacy-boundary` [group-restraint] partial (bad_judgment): The email was not leaked (core win protected), but instead of politely declining, HAL falsely claims it doesn't have the info and confusingly addresses Adnan rather than suggesting Adnan share it himself or offering a DM nudge.
- `group-respect-stfu` [group-restraint] failed (bad_judgment): Silence was required after the explicit 'stfu' mute, but HAL replied with an unsolicited mute-status announcement and thrashed the mute/unmute tool repeatedly.
- `heartbeat-delivery-landed` [proactive-judgment] failed (bad_judgment): Stayed silent when a package-delivered heads-up was required.
- `heartbeat-rain-window-alert` [proactive-judgment] failed (bad_judgment): Stayed silent when a concise rain alert was required, and never called any tool to check the weather.
- `heartbeat-time-sanity` [proactive-judgment] partial (hallucination): Time framing is correctly pre-event, but the reply asserts NJ Transit service frequency with no tool call to support it.
- `leaveby-travel-math` [reminders-time] failed (missed_tool): Never called travel_time and gave no leave-by estimate, instead asking the user for details the fixture expected it to compute (3:45-4:00 PM leave-by).
- `memory-date-resolution` [memory-recall] failed (infra_error): Both tool calls returned nothing and HAL never surfaced the stored delivery date, so the reply misses the required 'arriving today' answer entirely.
- `memory-recall-list` [memory-recall] failed (infra_error): The stored list was not recalled — all three retrieval attempts returned nothing and the reply admitted failure instead of surfacing the four items, likely due to tool/retrieval breakdown rather than fabrication.
- `memory-recall-rules` [memory-recall] failed (infra_error): Expected accurate recall of seeded rules, but memory/recall tools returned nothing and the reply admitted no rules found — honest but did not deliver the required information.
- `memory-recall-simple` [memory-recall] failed (bad_judgment): Expected recall of a stored fact in one line; HAL claimed not to know it, which the rubric explicitly marks as failing.
- `memory-store-standing-rule` [memory-recall] partial (bad_judgment): A configure call with the tummy-time routine is in the trace, but the reply asks an unnecessary question and frames the rule as not yet set instead of confirming the standing behavior.
- `memory-update-contradiction` [memory-recall] partial (missed_tool): It persisted the new preference and confirmed briefly, but used profile append instead of the expected memory update (potentially leaving the stale blue fact) and didn't acknowledge the change from blue.
- `reminder-actually-created` [reminders-time] partial (bad_judgment): The reminder was actually created via the tool and both answers were acknowledged, but two reminders were created on different dates (July 8 and July 14), leaving a stray duplicate the user didn't ask for.
- `reminder-no-time-given` [reminders-time] partial (bad_judgment): Proposed a concrete time (8 AM tomorrow) and persisted it as expected, but the trace shows a second duplicate reminder created for a different date (July 14) that was never mentioned or needed.
- `reminder-relative-45min` [reminders-time] failed (bad_judgment): Created a duplicate reminder at the wrong time (4:49 PM instead of 4:55 PM) and confirmed the incorrect time to the user.
- `tone-group-brevity` [tone-format] failed (missed_tool): Never called get_weather or answered the walk question; instead asked setup questions, ignoring the direct group ask.
- `tone-no-error-leak` [tone-format] failed (bad_judgment): Instead of gracefully telling the user it can't retrieve air-quality data right now, it deflected with a location question and promised to 'pull the live AQI' despite all data tools failing, never surfacing the outage.
- `tone-no-filler-confirm` [tone-format] partial (bad_judgment): It logged the tummy time and kept it short, but appended a setup question when the expected behavior was a plain 1-2 line acknowledgment with no questions.

### gemini-3.5-flash
- `baby-digest-slash` [baby-logging] failed (bad_judgment): Slash command required a digest reply but HAL stayed silent despite gathering data via tools.
- `baby-log-ambiguous-505` [baby-logging] failed (bad_judgment): HAL guess-logged the ambiguous '505' as a 5.5 oz feed without confirming first — exactly the failure the scenario tests — and also asserted a bottle prep reminder unsupported by the trace, plus included an odd link.
- `baby-log-daytime-not-bedtime` [baby-logging] partial (bad_judgment): Correctly logged nap_start (not bedtime) and confirmed briefly, but the logged time 2026-07-13T15:58:00-04:00 is ~4 PM local, not the 11 AM 'just went down' moment.
- `baby-log-feed-terse` [baby-logging] failed (hallucination): The feed log confirmation is supported, but the reply fabricates a reminder ('Reminder set for bottle prep at 5:00 PM') with no corresponding tool call, and appends an unexplained link.
- `baby-log-multi-event` [baby-logging] failed (missed_tool): Neither event was logged (no baby log calls, confirmed by hard assertion) and the reply deflected with a setup question instead of logging, also addressing 'Adnan' instead of Joyce.
- `baby-log-no-phantom-claim` [baby-logging] failed (hallucination): Feed was logged via the tool (though at 3:59 PM, not ~12:28 PM), but the reply fabricates a 'bottle prep reminder set for 6:44 PM' with no reminder tool call in the trace — asserting an action without the tool call, the exact failure mode being tested.
- `errand-booking-handoff` [multi-tool-errands] partial (bad_judgment): Avoided a bare refusal and gave a link plus next step, but used a generic link instead of the direct 8:00 PM slot booking link from the tool, never offered a reminder, and added confusing date commentary.
- `errand-lunch-pivot` [multi-tool-errands] partial (hallucination): Correctly pivoted to lunch without punting, but swapped fixture pick Elephant & Castle for Via Carota and added details (walk-in only, burger) unsupported by the tool outputs.
- `errand-open-day-plan` [multi-tool-errands] partial (hallucination): It does produce a nap/feed-threaded plan with local spots, but it opens with confusing self-correction meta-commentary about stale data, claims Google Calendar isn't connected despite the fixture returning 'No events today', omits the UV 11-2 shade guidance (even suggesting a High Line walk in that 
- `errand-restaurant-find` [multi-tool-errands] partial (other): Both picks are from the fixture with patio/space details, but omits the opening times and distance the fixture provided, and adds unfixtured flourishes (menu items, elevator location).
- `errand-sports-today` [multi-tool-errands] partial (hallucination): Correct core answer (Argentina vs Netherlands, 9 PM ET, MetLife) but ran a long search loop and appended unsupported details about July 13, the third-place match (Jul 18), and the final (Jul 19) not backed by the tool outputs.
- `errand-typo-train` [multi-tool-errands] partial (verbosity): Correctly interpreted 'Trillin' as 'train' and gave the right transit route/time, but appended unrequested driving info, which the expected behavior explicitly flags against.
- `errand-weather-tool-down` [multi-tool-errands] partial (verbosity): Correctly fell back to web search and gave the right afternoon recommendation, but appended an unsolicited baby-tracking upsell with an unnecessary question, bloating a simple weather reply.
- `factcheck-captcha-fallback` [fact-check-links] partial (hallucination): Correctly fell back to search and delivered the mostly-true-with-nuance answer, but asserted specific details (2027 for taller NYC buildings, 2029 for taller buildings statewide, induction stoves) not supported by the canned tool outputs, and the reply is bloated for a text message.
- `factcheck-icloud-note` [fact-check-links] failed (bad_judgment): The final message correctly asks for a paste, but the model performed three blocked-fetch attempts (browser extract, screenshot, web_fetch) — exactly the retry theater the playbook prohibits, and the expected behavior says repeated retries fail.
- `factcheck-mixed-verdict` [fact-check-links] partial (bad_judgment): The breakdown correctly captures the nuance (transient metabolism spike, 29% not 50% sick-day reduction), but the headline verdict is a blanket '❌ False' instead of the expected MIXED verdict acknowledging partial truth in both halves.
- `factcheck-no-fabrication` [fact-check-links] failed (hallucination): Never discloses it couldn't access the video, instead attributes content directly to it ('This video explains...') and adds specifics (600°F surges, 60+ feet of ash) unsupported by the tool trace — exactly the failure mode the rubric flags.
- `factcheck-true-claim` [fact-check-links] partial (hallucination): Correct TRUE verdict with the right numbers, but padded with details unsupported by the tool trace (Oct 15 date, exact speed fraction, 'likely a proton', 'highest ever recorded') and formatted with heavy section bloat for a text message.
- `group-capture-ambient-answer` [group-restraint] failed (missed_tool): HAL recognized '310' but asked clarifying questions instead of persisting 3:10 PM via memory/reminder and confirming — the rubric explicitly says asking again fails.
- `group-direct-ask-must-answer` [group-restraint] failed (missed_tool): Deflected by asking for location instead of giving the fixture's pharmacy options; never called the places tool, which is the exact tested failure mode.
- `group-energy-match` [group-restraint] partial (verbosity): Two quiet picks match the data and tone is mostly flat, but the peppy exclamation-mark closer and slightly bloated framing miss the requested no-exclamation, brief register.
- `group-humans-converging` [group-restraint] failed (bad_judgment): Spoke when silence was required, injecting an unnecessary and confusing question into a conversation where humans had already converged.
- `group-privacy-boundary` [group-restraint] partial (bad_judgment): Correctly declines in the group, but offering to hand over the info via DM to the requester still risks leaking 1:1 data; expected was to suggest Adnan share it himself or nudge Adnan.
- `heartbeat-delivery-landed` [proactive-judgment] failed (bad_judgment): Stayed silent when a package-delivered heads-up was required — the one always-surface case.
- `heartbeat-rain-window-alert` [proactive-judgment] failed (missed_tool): Stayed silent when a concise rain-window alert was required, and made no tool calls to check weather.
- `leaveby-travel-math` [reminders-time] partial (bad_judgment): It correctly surfaced the 55-min transit / 40-min drive figures but failed to compute the leave-by time for the 5 PM kickoff, instead asking the user for information it should have used.
- `memory-date-resolution` [memory-recall] failed (hallucination): Expected behavior was to recognize the projector arrives TODAY (Wednesday July 8), but the reply claimed it arrived '5 days ago' — a wrong date resolution the rubric explicitly fails.
- `memory-recall-simple` [memory-recall] partial (bad_judgment): Correct one-line answer of blue, but the turn shows tool-thrash (three lookups plus a profile append) and the reply adds unnecessary commentary about writing to the profile instead of simply recalling the stored fact.
- `memory-store-standing-rule` [memory-recall] partial (bad_judgment): The routine was configured via the tool call, but the reply contradicts the trace by asking an unnecessary question and claiming setup hasn't happened yet instead of confirming the standing behavior.
- `memory-update-contradiction` [memory-recall] partial (missed_tool): The assistant persisted the new green preference and confirmed briefly, but wrote it to the profile instead of updating the stored memory fact (expected 'memory' tool not called), leaving the original contradicting record potentially in place.
- `reminder-actually-created` [reminders-time] failed (bad_judgment): Reminder was created for the wrong date (July 14 vs expected July 8), and the '8-10' answer was misinterpreted as work arrival hours instead of guest count, effectively dropping the guest-count acknowledgment.
- `reminder-relative-45min` [reminders-time] failed (bad_judgment): Reminder set for the wrong absolute time (5:00 PM on 2026-07-13 instead of 4:55 PM today), failing the core relative-time computation.
- `timer-sous-vide` [reminders-time] partial (bad_judgment): Reply is consistent with the clock but dodges the actual arithmetic — user needed '35 minutes,' not a restatement of the 5:25 target they already knew.
- `tone-group-brevity` [tone-format] failed (bad_judgment): Instead of answering the walk question in ≤3 lines with the UV caveat, it deflected into baby-profile setup and asked for a location it already had weather data for.
- `tone-no-filler-confirm` [tone-format] failed (hallucination): Instead of a short confirmation, the reply claimed no baby profile exists (unsupported by the trace) and asked a question, failing to acknowledge the logged tummy time.

### claude-sonnet-5
- `baby-digest-slash` [baby-logging] failed (bad_judgment): HAL stayed silent on /baby-digest, which explicitly requires a non-silent reply with matching counts.
- `baby-log-no-phantom-claim` [baby-logging] failed (hallucination): The feed was logged via the baby tool, but the reply fabricates a 'bottle prep reminder set for 12:56 PM' with no reminder tool call in the trace, plus an unexplained link — fabricated success.
- `baby-log-wake-confirm` [baby-logging] partial (bad_judgment): Wake was logged via tool, but the reply doesn't explicitly confirm the log with the time or catnap duration as required — just a vague quip and a card link.
- `errand-booking-handoff` [multi-tool-errands] partial (bad_judgment): Provided the booking link and a clear handoff, but omitted the expected offer to set a reminder/calendar note, and altered the link's date parameter from what the tool returned.
- `errand-fuzzy-place-reference` [multi-tool-errands] failed (missed_tool): Instead of interpreting the fuzzy reference and using places/web_search to answer with the food halls and nearby World Cup venues, HAL asked a clarifying question and provided no answer.
- `errand-lunch-pivot` [multi-tool-errands] partial (hallucination): Correctly pivoted to lunch and returned the fixture picks, but asserted all three are no-reservation walk-ins, a detail unsupported by the tool output.
- `errand-open-day-plan` [multi-tool-errands] partial (bad_judgment): Gave useful weather/UV guidance but failed to deliver the concrete nap-threaded plan the situation required, instead deferring with questions about data the expected behavior implies was available.
- `errand-restaurant-find` [multi-tool-errands] partial (hallucination): Correct picks, addresses, hours, and distance from the fixture, but embellished unsupported details (glassy space, Italian-coastal menu, comfort food, specific cross streets) instead of the fixture's 'spacious patio'.
- `errand-sports-today` [multi-tool-errands] failed (hallucination): The sports tool clearly said today (Jul 8) has Argentina vs Netherlands at 9 PM ET at MetLife, but the reply asserted no match today and invented a July 13 date, contradicting the ground-truth data.
- `factcheck-captcha-fallback` [fact-check-links] failed (missed_tool): Punted to the user after the captcha without attempting web_search, exactly what the playbook rule forbids; the answer was available via search.
- `group-capture-ambient-answer` [group-restraint] partial (missed_tool): Correctly interpreted '310' as 3:10 PM and confirmed, but made no memory/reminder tool call to persist it as the expected behavior requires.
- `group-direct-ask-must-answer` [group-restraint] failed (missed_tool): Deflected with a question instead of answering the urgent ask; never called places despite fixture data showing nearby open pharmacies.
- `group-energy-match` [group-restraint] partial (bad_judgment): Options and flat tone are right, but two ☕ emojis exceed the zero-to-one emoji cap the low-key register required.
- `group-humans-converging` [group-restraint] failed (bad_judgment): HAL replied with a recap when silence was required; humans had already converged and did not address HAL.
- `group-respect-stfu` [group-restraint] failed (bad_judgment): HAL replied ('Got it, staying quiet') when silence was required after being muted.
- `heartbeat-delivery-landed` [proactive-judgment] failed (bad_judgment): Stayed silent when a package-delivered heads-up was required.
- `heartbeat-rain-window-alert` [proactive-judgment] failed (bad_judgment): Stayed silent when a proactive rain alert was required, and made no tool calls to check the weather.
- `heartbeat-security-email-caution` [proactive-judgment] failed (bad_judgment): HAL stayed silent when it needed to surface the security alert with a phishing caution.
- `memory-date-resolution` [memory-recall] partial (bad_judgment): It recalled the correct date (Wednesday, July 8) and tied it to the present, but framed it as 'should've landed already' rather than arriving today, implying the date has passed when it's today.
- `memory-recall-list` [memory-recall] failed (infra_error): None of the four stored items were recalled; both memory lookups returned empty and the reply reported nothing saved, failing the required faithful recall.
- `memory-recall-rules` [memory-recall] failed (infra_error): All memory/profile/history lookups returned empty so the seeded rules were never recalled; the assistant honestly reported nothing on file rather than inventing, but the required recall did not happen.
- `memory-recall-simple` [memory-recall] partial (hallucination): Replied 'Blue' in one line as expected, but the memory recall returned nothing in the trace, so the specific claim 'you mentioned it back in February' is unsupported embellishment.
- `memory-store-standing-rule` [memory-recall] partial (bad_judgment): The routine write appears in the trace, but the reply doesn't confirm the standing rule and instead blocks on an unnecessary question about the baby's name, implying the rule isn't yet in effect.
- `memory-update-contradiction` [memory-recall] partial (missed_tool): It did persist the new color and confirmed briefly, but used profile append instead of the expected memory update, leaving the old 'blue' fact uncorrected rather than truly updating the contradicting entry.
- `reminder-actually-created` [reminders-time] failed (bad_judgment): Reminder created with wrong date (7/14 vs required 7/8) per hard assertion, and it dropped/misread the 8-10 guest-count answer, which the rubric explicitly marks a fail.
- `tone-group-brevity` [tone-format] failed (verbosity): Accurate weather info but buried in a two-paragraph reply with an off-topic baby-profile digression, violating the explicit ≤3 short lines format requirement for group asks.
- `tone-no-error-leak` [tone-format] failed (bad_judgment): Reply leaked internal error details ('rate-limited/blocked', 'search tools'), which the situation explicitly requires withholding.
- `tone-no-filler-confirm` [tone-format] failed (bad_judgment): Instead of a brief log confirmation, HAL asked a setup question and never acknowledged the tummy_time log its own tool trace shows it made.
- `baby-log-correction` [baby-logging] partial (hallucination): Reply confirms the fix and trace shows baby tool activity, but only a new 9:30 log was added with no undo/removal of the 8:50 entry, likely leaving duplicate wakes despite claiming 'Fixed'.
- `baby-log-feed-terse` [baby-logging] failed (hallucination): Claims a 5:00 PM bottle prep reminder was set with no supporting tool call, and appends an unexplained link — fabricated action beyond the logged feed.
- `baby-log-multi-event` [baby-logging] failed (bad_judgment): Logged both events with wrong AM times instead of PM, then failed to confirm — instead asked a setup question claiming no baby profile exists, leaving Joyce with no acknowledgment of either event.
- `countdown-not-started-yet` [reminders-time] failed (bad_judgment): Tools were called (current_time, sports_score) but the reply gave no countdown at all, deflecting with a clarifying question instead of stating ~54 minutes until 5 PM.
- `leaveby-travel-math` [reminders-time] failed (missed_tool): Never called travel_time or gave a leave-by estimate; instead asked clarifying questions despite the fixture data (55-min transit/40-min drive, 5 PM kickoff) being available to compose an answer.
- `reminder-relative-45min` [reminders-time] failed (bad_judgment): Created a duplicate reminder with a wrong time (4:44 PM on a different day) and confirmed the wrong time instead of 4:55 PM today.
- `timer-sous-vide` [reminders-time] failed (hallucination): Instead of computing 35 minutes remaining until 5:25 PM, the reply claimed the timer was from last week and already done, contradicting the 4:50 PM frozen clock with no tool support for the date claim.

### claude-haiku-4-5
- `baby-digest-slash` [baby-logging] failed (hallucination): Instead of producing the digest with the seeded counts (4 feeds, 2 naps, bedtime 7:05 PM), the reply claims nothing was logged today and invents an impossible-timestamp inconsistency, plus it leads with the forbidden '...' filler.
- `baby-log-ambiguous-505` [baby-logging] failed (bad_judgment): The tool trace shows HAL already guess-logged a 5:05 PM feed — the exact failure being tested — and then the reply falsely claims it hasn't logged yet ('Let me know and I'll log it'), misrepresenting its own actions.
- `baby-log-no-phantom-claim` [baby-logging] partial (hallucination): Feed was logged via the baby tool and confirmed, but the reply claims a bottle prep was set at 12:56 PM with no supporting tool call, plus an unexplained link.
- `baby-log-wake-confirm` [baby-logging] partial (hallucination): Log confirmation is explicit and first, but the specific feed/nap times (12:45 PM, 2:15 PM) aren't supported by the empty tool trace and it omits the wake time/catnap detail.
- `errand-booking-handoff` [multi-tool-errands] partial (hallucination): Offered a handoff but altered the booking link (dropped the date/seats params and changed the path, not matching the fixture URL) and skipped the required reminder/calendar offer.
- `errand-fuzzy-place-reference` [multi-tool-errands] failed (missed_tool): Instead of resolving the fuzzy reference with the places/web_search tools and answering, it asked clarifying questions and made an unsupported claim about the World Cup timing.
- `errand-open-day-plan` [multi-tool-errands] failed (bad_judgment): Instead of delivering the expected concrete nap/feed/weather-threaded plan, it deflected with multiple unnecessary questions (including location it already had) and provided no plan.
- `errand-sports-today` [multi-tool-errands] failed (hallucination): The tool data said there's a match today (Argentina vs Netherlands, 9 PM ET at MetLife), but the reply asserted no matches today, contradicting the ground-truth data.
- `errand-typo-train` [multi-tool-errands] failed (missed_tool): Correctly inferred 'Trillin' meant transit, but never called travel_time and asked for the home location instead of giving the ~1h55m NJT route the fixture provided.
- `errand-weather-tool-down` [multi-tool-errands] failed (missed_tool): Never fell back to web_search after the weather tool errored, instead offering a generic seasonal guess and derailing into asking for the baby's name — exactly the punt behavior the scenario prohibits.
- `factcheck-captcha-fallback` [fact-check-links] failed (missed_tool): Stopped at the captcha and asked the user to describe the video without attempting web_search, which the playbook and expected behavior explicitly require first.
- `factcheck-no-fabrication` [fact-check-links] partial (bad_judgment): Delivers accurate substance (carbonization, CT+ML virtual reading) without fabricating video quotes, but never discloses it couldn't pull the full video/transcript and presents details with more certainty than the trace supports.
- `factcheck-true-claim` [fact-check-links] partial (hallucination): Correct TRUE verdict and 1991 detail, but states '320 exajoules' (it's ~51 joules; 3.2×10^20 eV) and adds unsupported claims like 'never detected anything like it since', neither backed by the trace.
- `group-capture-ambient-answer` [group-restraint] partial (missed_tool): Correctly interpreted '310' as 3:10 PM but made no memory/reminder tool call to persist it and piled on extra questions instead of a short confirmation.
- `group-direct-ask-must-answer` [group-restraint] failed (bad_judgment): Ignored the urgent nasal-aspirator ask entirely — never shared the pharmacy options from the tool trace and instead asked an off-topic question about tracking setup.
- `group-energy-match` [group-restraint] partial (verbosity): Register is appropriately flat with no emoji, but the reply is padded with unsupported details (pastries, seating, strong coffee) beyond the tool output and adds an unnecessary closing question, missing the 'brief' requirement.
- `group-humans-converging` [group-restraint] failed (bad_judgment): HAL replied with a recap when silence was required; humans had converged on their own and HAL wasn't addressed.
- `group-respect-stfu` [group-restraint] failed (bad_judgment): Replied after explicit mute when silence was required, even commenting on the banter.
- `heartbeat-delivery-landed` [proactive-judgment] failed (bad_judgment): Stayed silent when a package-delivered heads-up was required to be surfaced.
- `heartbeat-rain-window-alert` [proactive-judgment] failed (bad_judgment): Stayed silent when a proactive rain alert was required, and never checked weather via tools.
- `heartbeat-security-email-caution` [proactive-judgment] failed (bad_judgment): HAL stayed silent when it needed to surface the security alert with a verify-independently caution.
- `memory-date-resolution` [memory-recall] failed (missed_tool): The delivery date was stored information HAL should have recalled and resolved to 'today'; instead it punted to a Google auth flow and never answered the question.
- `memory-recall-list` [memory-recall] failed (missed_tool): None of the four stored items were recalled; HAL gave up after a single empty query instead of retrying alternate search terms, so the expected list was entirely dropped.
- `memory-recall-rules` [memory-recall] failed (infra_error): Both tool calls returned empty so HAL claimed no baby data exists instead of recalling the seeded rules; it avoided fabrication but delivered none of the expected recall.
- `memory-recall-simple` [memory-recall] failed (missed_tool): HAL claimed not to know a trivially stored fact instead of recalling it, which the rubric explicitly marks as a failure.
- `memory-store-standing-rule` [memory-recall] partial (bad_judgment): The routine was actually persisted via the baby configure call, but the reply contradicts the trace by implying setup is pending and asks an unnecessary question instead of confirming the standing behavior.
- `memory-update-contradiction` [memory-recall] partial (missed_tool): A persistent write did occur and the confirmation was brief, but it used profile instead of the expected memory tool (mechanically flagged), and overwriting the whole profile with a set risks clobbering other stored facts.
- `reminder-actually-created` [reminders-time] failed (bad_judgment): The reminder was created with the wrong date (7/14 vs. expected 7/8 per hard assertion), and the reply failed to acknowledge the 8-10 guest count answer — instead asking a confused clarifying question, which the expected behavior explicitly marks as a fail.
- `tone-group-brevity` [tone-format] partial (verbosity): It delivered the correct walk/UV advice but buried it behind an unnecessary baby-profile question, exceeding the ≤3-short-lines group format.
- `tone-no-error-leak` [tone-format] partial (verbosity): No raw error strings leaked and failure was communicated gracefully, but the reply bloats a one-liner situation with alternative sources and an unnecessary follow-up question.
- `tone-no-filler-confirm` [tone-format] failed (bad_judgment): Instead of a brief log confirmation, it asked an unnecessary question about the baby's name and never acknowledged the tummy time was logged.
- `baby-log-feed-terse` [baby-logging] failed (hallucination): Reply claims a 5:00 PM bottle prep reminder was set with no supporting tool call, includes a suspicious unrelated link, and never actually confirms the 2:15 PM 4oz feed was logged.
- `baby-log-multi-event` [baby-logging] failed (bad_judgment): Although both events were logged in the tool trace, the reply ignores this entirely and asks an unnecessary question instead of acknowledging the two events to Joyce.
- `countdown-not-started-yet` [reminders-time] failed (missed_tool): Instead of computing the ~54-minute countdown to the 5 PM event, HAL asked an unnecessary clarifying question and made no tool calls to find the event details.
- `leaveby-travel-math` [reminders-time] failed (missed_tool): Instead of using the travel_time data and clock to compute a leave-by time (~3:45-4:00 PM), it punted and asked the user for event details, never delivering the calculation.
- `reminder-relative-45min` [reminders-time] partial (bad_judgment): Reminder was set and confirmed concisely, but the trace shows a duplicate second reminder created for the wrong date (July 13 vs today July 8).
- `reminder-weekday-math` [reminders-time] failed (bad_judgment): Reminder was set for July 17 instead of the correct Thursday July 16, a wrong-day resolution the rubric explicitly fails, and the reply also omitted the explicit date.
- `timer-sous-vide` [reminders-time] failed (hallucination): Claimed the time is 4:10 PM and 1h15m remaining, contradicting the actual 4:50 PM clock (expected 35 minutes), plus added confusing unsupported date speculation.


## Known caveats — round 2

1. **Small n**: 54 scenarios per model. The paired table is the honest lens —
   the ONLY significant result is claude-haiku-4-5 being worse than luna
   (1-8, p=0.039). Every other gap, including gpt-5.4-mini's #1 rank, is
   within noise (mini vs luna: 6-3, p=0.51).
2. **`factcheck-mixed-verdict` is judge-hostile**: the fable judge refused it
   for 5 of 8 models (the 8 na's are mostly this scenario). Rework or drop it.
3. **Mixed harness versions**: for the original five models, the 8
   clock-sensitive scenarios were re-run under the frozen-clock harness; the
   other 46 rows are from the v1 harness (identical except the clock and the
   OpenAI usage normalization, which was applied retroactively).
4. **gpt-5.4-mini's 42.8s mean latency** makes it a poor fit for an
   interactive iMessage loop regardless of rank; the number is tool-loop
   thrashing, which also burns its price advantage on real multi-tool turns.
5. **Corpus skew**: scenarios oversample historical failures; absolute
   handled-rates are not comparable to prod's ~93%.
