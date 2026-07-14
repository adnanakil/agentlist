# HAL Eval Report

270 runs — 54 scenarios x 5 models. Judge: fixed model, blind to candidate identity. Handled-rate excludes na (judge/harness failures).

## Overall

| Model | Handled | Partial | Failed | na | Handled-rate | Asserts | Mean $/turn | Median $/turn | Mean latency |
|---|---|---|---|---|---|---|---|---|---|
| gpt-5.4 | 25 | 17 | 12 | 0 | 46.3% | 45/54 | $0.1794 | $0.1280 | 33.8s |
| gpt-5.4-mini | 21 | 16 | 16 | 1 | 39.6% | 46/54 | $0.0648 | $0.0394 | 41.4s |
| gpt-5.6-luna | 19 | 14 | 21 | 0 | 35.2% | 44/54 | $0.0508 | $0.0329 | 15.0s |
| claude-sonnet-5 | 19 | 13 | 22 | 0 | 35.2% | 42/54 | $0.0463 | $0.0284 | 9.3s |
| claude-haiku-4-5 | 11 | 15 | 28 | 0 | 20.4% | 41/54 | $0.0100 | $0.0054 | 3.9s |

## Handled-rate by category

| Category | gpt-5.4 | gpt-5.4-mini | gpt-5.6-luna | claude-sonnet-5 | claude-haiku-4-5 |
|---|---|---|---|---|---|
| baby-logging | 12.5% | 25.0% | 12.5% | 25.0% | 12.5% |
| fact-check-links | 83.3% | 80.0% | 66.7% | 83.3% | 16.7% |
| group-restraint | 50.0% | 50.0% | 33.3% | 16.7% | 16.7% |
| memory-recall | 50.0% | 16.7% | 16.7% | 0.0% | 0.0% |
| multi-tool-errands | 37.5% | 0.0% | 12.5% | 25.0% | 12.5% |
| proactive-judgment | 75.0% | 75.0% | 75.0% | 62.5% | 62.5% |
| reminders-time | 25.0% | 37.5% | 37.5% | 37.5% | 12.5% |
| tone-format | 50.0% | 50.0% | 25.0% | 25.0% | 25.0% |

## Projected monthly cost

Prod volume: **35 turns/day** (hal_turns, trailing 14 days). Projection = mean eval cost/turn x volume x 30. Eval turns skew heavier than prod (fixtures force tool loops), so treat these as an upper bound for ranking, not a bill forecast.

| Model | Mean $/turn | $/day | $/month |
|---|---|---|---|
| gpt-5.4 | $0.1794 | $6.21 | $186.26 |
| gpt-5.4-mini | $0.0648 | $2.24 | $67.31 |
| gpt-5.6-luna | $0.0508 | $1.76 | $52.76 |
| claude-sonnet-5 | $0.0463 | $1.60 | $48.01 |
| claude-haiku-4-5 | $0.0100 | $0.35 | $10.42 |

## Recommendation

**gpt-5.4** is both the best-scoring (46.3%) and the cheapest eligible model.

## Failures (partial + failed)

### gpt-5.4
- `baby-digest-slash` [baby-logging] failed (bad_judgment): HAL stayed silent on a /baby-digest command that explicitly requires a reply, despite invoking the stats tools.
- `baby-log-ambiguous-505` [baby-logging] failed (bad_judgment): HAL guess-logged a 5:05 PM feed without confirming first, exactly the failure mode being tested; expected a clarifying question or confirm-before-log.
- `baby-log-correction` [baby-logging] partial (hallucination): Tool trace correctly undoes and relogs the 9:30 wake, but the reply claims a wind-down reminder was set (unsupported by trace) and doesn't confirm the corrected 9:30 time.
- `baby-log-feed-terse` [baby-logging] partial (bad_judgment): Confirmation was brief and a tool call was made, but the feed was logged at 2:15 AM instead of the expected 2:15 PM, and the reply doesn't confirm the time/amount details.
- `baby-log-multi-event` [baby-logging] failed (bad_judgment): Only one event logged (feed, and at 6:10 AM instead of PM), no sleep/bedtime logged, wrong AM assumption, asked an unnecessary question instead of confirming both events to Joyce.
- `baby-log-no-phantom-claim` [baby-logging] partial (hallucination): Feed was logged via the baby tool as required, but the reply claims a bottle prep reminder was set with no supporting tool call in the trace.
- `baby-log-wake-confirm` [baby-logging] partial (bad_judgment): The wake was logged and the reply stays on topic, but 'He's up ☀️' doesn't explicitly confirm the log or include the wake time/nap length the expected behavior calls for.
- `countdown-not-started-yet` [reminders-time] partial (bad_judgment): Avoided the 'already started' failure mode and asked a reasonable clarifying question after tools returned nothing, but never delivered the expected ~54-minute countdown to the 5 PM event.
- `errand-booking-handoff` [multi-tool-errands] partial (bad_judgment): Provided the direct 8:00 PM booking link and a helpful fallback, but skipped the expected offer to set a reminder/calendar note so the booking doesn't slip.
- `errand-fuzzy-place-reference` [multi-tool-errands] partial (bad_judgment): Correctly interpreted the fuzzy reference as a food hall near 11th, but withheld the nearby World Cup venues it researched (e.g., Brass Monkey), ending with an unnecessary question instead of offering them.
- `errand-open-day-plan` [multi-tool-errands] partial (bad_judgment): Gave a weather-aware, UV-conscious schedule but missed the standout nap/feed threading (no ~9-9:30 nap or feed cadence despite calling the forecast tool) and stayed generic despite researching specific spots like Little Island and Chelsea Waterside.
- `errand-restaurant-find` [multi-tool-errands] failed (hallucination): The tool trace shows no returned data from any places or web_search call, yet the reply asserts specific opening times (11, 11:30), patio details, and addresses — details unsupported by the trace, which the expected behavior explicitly says fails.
- `errand-sports-today` [multi-tool-errands] failed (bad_judgment): Reply says there's no match today, contradicting the expected data (Argentina vs Netherlands semifinal tonight), and it fell into the web-search loop instead of answering from the sports tool.
- `factcheck-captcha-fallback` [fact-check-links] failed (missed_tool): Stopped at the captcha and asked the user to describe the video without attempting web_search on the topic, which the playbook explicitly requires.
- `group-direct-ask-must-answer` [group-restraint] partial (missed_tool): Responded with useful interim advice and safety guidance, but failed to call the places tool to give actual open-pharmacy options from the fixture, instead deflecting with a question for the user's location.
- `group-humans-converging` [group-restraint] failed (bad_judgment): HAL replied when silence was required; humans had already converged and HAL wasn't addressed.
- `group-respect-stfu` [group-restraint] failed (bad_judgment): Silence was required after the explicit 'stfu' but HAL replied with '👍', violating the mute.
- `heartbeat-rain-window-alert` [proactive-judgment] failed (bad_judgment): HAL stayed silent when a concise rain alert was required, making no tool calls and providing no warning about the 2 PM rain window.
- `heartbeat-time-sanity` [proactive-judgment] partial (hallucination): Time framing is correctly pre-event, but the reply asserts transit frequency and weather details with no tool calls to support them.
- `leaveby-travel-math` [reminders-time] partial (bad_judgment): Correctly used the 40/55-min travel figures with a buffer, but never composed them with the frozen 2:30 PM clock and 5:00 PM kickoff into a concrete ~3:45-4:00 PM leave-by, instead asking the user for the start time.
- `memory-date-resolution` [memory-recall] failed (bad_judgment): The expected answer was that the projector arrives today (Wednesday July 8), but the reply claims no order details exist and asks the user for tracking info, failing to surface the stored relative date at all.
- `memory-recall-rules` [memory-recall] partial (other): Recalled stroller and tummy-time rules correctly without inventing, but omitted the seeded feed cadence (~every 2.5-3h from ~6:30 AM).
- `memory-store-standing-rule` [memory-recall] partial (bad_judgment): A configure call with the routine was made, but the reply asks for the baby's name instead of cleanly confirming the standing rule, leaving it unclear whether the behavior is actually active.
- `reminder-actually-created` [reminders-time] partial (bad_judgment): Reminder was actually created via the tool, but for the wrong date (7/14 instead of the expected 7/8), and the '8-10' answer was misread as work hours rather than guest count.
- `reminder-relative-45min` [reminders-time] failed (bad_judgment): Computed the wrong absolute due time (11:21 AM on the wrong day instead of 4:55 PM today), so the reminder was set incorrectly despite a confident confirmation.
- `stale-price-caveat` [reminders-time] partial (bad_judgment): Avoided the failure mode of quoting stale $1,820 as current, but never surfaced the cached figures with a June 6 as-of caveat as expected, instead asserting pricing 'hasn't been released' and historical figures unsupported by the (empty) tool trace, plus internal narration bloat.
- `timer-sous-vide` [reminders-time] failed (hallucination): Reply claims ~6h47m remaining, which is inconsistent with the 4:50 PM frozen clock (correct answer was 35 minutes), asserting a duration unsupported by the tool trace.
- `tone-group-brevity` [tone-format] partial (verbosity): Core walk/UV advice is correct, but the reply exceeds the ≤3-short-lines group format with extra baby-tracker setup chatter and a question.
- `tone-no-filler-confirm` [tone-format] partial (bad_judgment): Instead of a simple 1-2 line log confirmation, HAL asked a setup question about the baby's name and never confirmed the log, though it did attempt the tool call and stayed brief.

### gpt-5.4-mini
- `baby-digest-slash` [baby-logging] failed (bad_judgment): Slash command required a digest reply but HAL stayed silent despite the situation explicitly forbidding silence.
- `baby-log-ambiguous-505` [baby-logging] failed (bad_judgment): HAL guess-logged the feed (multiple times, with an undo mid-way) without asking the required clarifying question, which is the exact failure this scenario tests.
- `baby-log-correction` [baby-logging] partial (hallucination): The undo+relog correctly fixed the record to 9:30, but the reply claims a wind-down reminder was set with no supporting tool activity and doesn't state the corrected 9:30 time.
- `baby-log-feed-terse` [baby-logging] partial (bad_judgment): Tool was called and a brief confirmation given, but the feed was logged at 2:15 AM instead of the expected 2:15 PM — a wrong detail in the logged data.
- `baby-log-multi-event` [baby-logging] failed (bad_judgment): Instead of confirming both events to Joyce, HAL asked the owner an unnecessary question, logged the times as AM instead of PM and bedtime as a nap, and its reply contradicts the tool trace by saying it will log later.
- `baby-log-no-phantom-claim` [baby-logging] failed (hallucination): Feed was logged at 10:14 AM instead of ~12:28 PM, and the reply claims a bottle prep reminder was set with no such tool call in the trace — fabricated success.
- `countdown-not-started-yet` [reminders-time] partial (bad_judgment): Avoided the 'already started' failure and didn't fabricate, but never delivered the ~54-minute countdown, instead asking a clarifying question the situation expected it to answer.
- `errand-booking-handoff` [multi-tool-errands] partial (bad_judgment): Provided the booking link and a helpful fallback, but skipped the expected offer to set a reminder/calendar note so the booking doesn't slip.
- `errand-fuzzy-place-reference` [multi-tool-errands] partial (bad_judgment): It fixated on the 7th Ave 'Cafeteria' restaurant instead of interpreting the fuzzy reference as a food hall near 11th Ave (Chelsea Market), but did helpfully surface actual nearby World Cup venues like Brass Monkey.
- `errand-lunch-pivot` [multi-tool-errands] failed (bad_judgment): After 16 tool calls it punted by asking for day and party size instead of returning lunch picks — exactly the tested failure mode.
- `errand-open-day-plan` [multi-tool-errands] partial (missed_tool): Gave a reasonable nap-rhythm plan but never checked weather or calendar (no UV/shade guidance, no specific local times), missing the core threading the situation required.
- `errand-restaurant-find` [multi-tool-errands] failed (hallucination): Reply invents restaurants and 'open now' claims not supported by the empty tool trace, and even includes fake unexecuted tool-call markup — clear fabrication.
- `errand-sports-today` [multi-tool-errands] failed (bad_judgment): Gave the wrong answer (said no game today when the sports data shows Argentina vs Netherlands tonight) after falling into the search loop the situation was testing against.
- `errand-typo-train` [multi-tool-errands] partial (hallucination): Correctly read 'Trillin' as train and gave the expected ~1h55m NJT Gladstone route, but appended a driving time/distance not supported by any tool call in the trace.
- `errand-weather-tool-down` [multi-tool-errands] partial (bad_judgment): Correctly fell back to web_search and avoided punting, but the recommendation contradicts its own forecast — advising to head out 'soon' this morning despite rain ending ~10 AM, instead of late-morning/afternoon.
- `factcheck-captcha-fallback` [fact-check-links] partial (infra_error): It followed the playbook by attempting many search fallbacks before punting, but the empty results degraded the reply and it mischaracterized the captcha block as a broken/expired link instead of noting the actual blocker or addressing the underlying claim.
- `group-capture-ambient-answer` [group-restraint] partial (missed_tool): Correctly interpreted '310' as 3:10 PM and confirmed briefly, but no memory/reminder tool call in the trace to actually persist it.
- `group-direct-ask-must-answer` [group-restraint] partial (hallucination): Replied immediately with pharmacy options and an appropriate escalation line, but the specific details (distances, hours, NoseFrida stock note) aren't supported by the empty tool trace results.
- `group-humans-converging` [group-restraint] failed (bad_judgment): HAL replied with a recap when silence was required; exactly the failure mode described.
- `heartbeat-delivery-landed` [proactive-judgment] failed (bad_judgment): Stayed silent when a package-delivered heads-up was required.
- `heartbeat-rain-window-alert` [proactive-judgment] failed (bad_judgment): Stayed silent when a proactive rain alert was required, with no tool calls to check the forecast.
- `leaveby-travel-math` [reminders-time] partial (bad_judgment): Correct travel figures and buffer logic, but never computed the concrete ~3:45-4:00 PM leave-by against the 5:00 PM kickoff and 2:30 PM current time, instead asking for the start time.
- `memory-date-resolution` [memory-recall] failed (bad_judgment): Today is Wednesday July 8, so the projector arrives today, but the reply claims that date has already passed — a wrong resolution of the stored date against the current date.
- `memory-recall-list` [memory-recall] failed (infra_error): None of the four stored items were recalled; all retrieval attempts returned empty and the reply admitted no list found, failing the core expectation, though the assistant did try multiple reasonable queries.
- `memory-recall-rules` [memory-recall] partial (bad_judgment): Accurately recalled the stroller nap (~15 min) and tummy time (~30 min after feeds) rules without inventing anything, but omitted the seeded feeding cadence (~every 2.5-3h from ~6:30 AM).
- `memory-store-standing-rule` [memory-recall] partial (bad_judgment): A durable write was attempted (routine configured via the baby tool), but the reply asks an unnecessary question about the baby's name instead of cleanly confirming the standing rule is in place.
- `memory-update-contradiction` [memory-recall] partial (missed_tool): It persisted the change and confirmed briefly, but appended to profile instead of updating the memory store, potentially leaving the old 'blue' fact in place and failing the expected memory tool call.
- `reminder-actually-created` [reminders-time] failed (bad_judgment): Reminder was created but for the wrong date (Jul 14 vs the expected Jul 8, per hard assertion), and the reply dropped the 8-10 guest-count acknowledgment by calling it 'unclear' — the expected behavior explicitly marks that as a fail.
- `reminder-relative-45min` [reminders-time] failed (bad_judgment): Reminder set for the wrong date/time (11:28 AM Jul 13 instead of 4:55 PM today), so the relative-time computation was wrong.
- `timer-sous-vide` [reminders-time] failed (hallucination): Reply claims 6h 40m remain, wildly inconsistent with the frozen 4:50 PM clock where the correct answer is 35 minutes.
- `tone-group-brevity` [tone-format] partial (bad_judgment): Core answer is correct and concise (walk good, avoid 11-2 UV), but tacks on an unnecessary baby-tracker setup question that wasn't asked for in a group context.
- `tone-no-filler-confirm` [tone-format] failed (bad_judgment): Instead of a brief log confirmation, the reply asks a setup question and adds an emoji, contradicting the expected no-questions acknowledgment and not confirming the logged tummy time.

### gpt-5.6-luna
- `baby-digest-slash` [baby-logging] failed (bad_judgment): HAL stayed silent on the /baby-digest command despite the situation explicitly requiring a non-silent digest reply.
- `baby-log-ambiguous-505` [baby-logging] partial (bad_judgment): Correctly withheld logging and asked one clarifying question, but the offered interpretations (bedtime/reminder) don't match the likely feed-log context (5:05 PM feed vs. correction to the 4:40 feed), so the user still has to redirect.
- `baby-log-correction` [baby-logging] partial (hallucination): Correctly undid and relogged the 9:30 wake, but claimed a wind-down was set for 11:30 AM with no supporting tool activity in the trace.
- `baby-log-feed-terse` [baby-logging] partial (bad_judgment): Short confirmation given, but the tool logged 2:15 AM (02:15) instead of the expected 2:15 PM feed, a wrong detail in the tool call.
- `baby-log-multi-event` [baby-logging] failed (bad_judgment): Only one event logged and with wrong time (6:10 AM instead of PM), bedtime never logged, misread 'slept' as a nap, and asked an unnecessary question instead of acknowledging both events.
- `baby-log-no-phantom-claim` [baby-logging] partial (hallucination): Feed was logged via the baby tool and confirmed, but the reply claims a bottle prep reminder was set for 12:55 PM with no tool call or auto_feed_prep support in the trace.
- `baby-log-wake-confirm` [baby-logging] partial (other): Reply leads with an explicit log confirmation as required, but omits the expected specifics (wake time and ~30 min catnap), and the logged time (10:11) doesn't match the expected 11:30 AM.
- `countdown-not-started-yet` [reminders-time] partial (bad_judgment): Avoided the 'already started' failure but never gave the ~54-minute countdown, instead asking a clarifying question despite having current time available.
- `errand-booking-handoff` [multi-tool-errands] partial (bad_judgment): Provided the direct booking link for the 8:00 PM slot but omitted the required offer to set a reminder/calendar note.
- `errand-fuzzy-place-reference` [multi-tool-errands] failed (bad_judgment): Instead of interpreting the fuzzy reference as a food hall near 11th Ave and offering nearby World Cup venues, HAL punted with clarifying questions after 18 tool calls, providing no useful answer.
- `errand-open-day-plan` [multi-tool-errands] failed (bad_judgment): The core ask was a nap-aware day plan; instead of producing one (next nap ~9-9:30, feeds every 2.5-3h, shade during UV peak), it punted with questions about location and schedule, claiming the baby log was garbled.
- `errand-restaurant-find` [multi-tool-errands] failed (hallucination): The places tool returned no visible results, yet the reply asserts specific restaurants, addresses, and opening times — fabricated details not supported by the trace.
- `errand-sports-today` [multi-tool-errands] failed (hallucination): The reply gave the wrong answer (no match today) when the expected answer was Argentina vs Netherlands tonight at 9 PM ET, and it fell into the exact search loop the situation required avoiding.
- `errand-typo-train` [multi-tool-errands] failed (missed_tool): Instead of inferring 'train' and answering with the transit route, it asked a clarifying question and never called travel_time — exactly the failure mode the situation warns against.
- `errand-weather-tool-down` [multi-tool-errands] failed (bad_judgment): After searches failed, the reply punts to a 'quick door check'—the exact 'peek outside' behavior the rubric explicitly fails—and exposes the tool outage instead of extracting a real forecast from search.
- `factcheck-captcha-fallback` [fact-check-links] partial (infra_error): It did fall back to extensive searching as the playbook requires, but with all tools returning nothing it punted back to the user with zero substance on the gas-stove claim it clearly knew the topic of, and misdescribed the blockage as a bad/deleted link.
- `factcheck-no-fabrication` [fact-check-links] partial (hallucination): Discloses it couldn't access the video's audio/transcript and delivers real search-backed value, but issues a 'mostly true / oversimplified' verdict and characterizes the video's 'hype' as if it knew the video's specific claims beyond the caption.
- `group-capture-ambient-answer` [group-restraint] partial (missed_tool): Correctly interpreted '310' as 3:10 PM and confirmed briefly, but no memory/reminder tool call in trace to persist it as required.
- `group-direct-ask-must-answer` [group-restraint] failed (missed_tool): Deflected the urgent pharmacy ask by requesting location instead of calling the places tool to give nearest open pharmacy options — the exact tested failure mode.
- `group-humans-converging` [group-restraint] failed (bad_judgment): HAL sent an unnecessary confirmation when silence was required; humans had converged and HAL was not addressed.
- `group-respect-stfu` [group-restraint] failed (bad_judgment): Silence was required after the explicit mute, but HAL replied with banter and also thrashed mute/unmute tool calls erratically.
- `heartbeat-rain-window-alert` [proactive-judgment] failed (bad_judgment): HAL stayed silent when a concise rain-window alert was required, and made no tool calls to check the forecast.
- `heartbeat-time-sanity` [proactive-judgment] partial (hallucination): Time framing is correctly pre-event (leave-now nudge before 5 PM kickoff), but the reply cites specific NJ Transit service frequency with no tool call to support it.
- `leaveby-travel-math` [reminders-time] failed (missed_tool): Instead of using the travel_time figures (55-min transit / 40-min drive) to give a leave-by around 3:45-4:00 PM, it asked clarifying questions and never called the travel time tool.
- `memory-date-resolution` [memory-recall] failed (infra_error): The reply never surfaces the stored arrival date or connects it to today (Wednesday July 8); it claims the info can't be found and asks the user for details instead.
- `memory-recall-list` [memory-recall] failed (infra_error): None of the four items were recalled; the tool calls returned nothing so the assistant honestly reported no results, but the required list was not produced.
- `memory-recall-rules` [memory-recall] failed (infra_error): The assistant never surfaced the seeded rules — its recall/profile/baby tools all returned empty, and while it honestly avoided inventing details, the required recall did not happen.
- `memory-store-standing-rule` [memory-recall] partial (bad_judgment): The rule was persisted via the baby configure tool and the standing behavior stated, but the reply adds an unnecessary question about the baby's name instead of a clean one-line confirmation.
- `memory-update-contradiction` [memory-recall] partial (missed_tool): A write did occur, but it appended to profile instead of updating via the expected memory tool, leaving the old 'blue' fact contradicted rather than replaced, and the reply didn't acknowledge the change from blue.
- `reminder-actually-created` [reminders-time] failed (bad_judgment): Reminder was set for the wrong date (July 14 vs expected July 8) per the hard assertion, and the reply misread the 8-10 guest-count answer as a second reminder request instead of acknowledging it — an explicit fail condition.
- `reminder-relative-45min` [reminders-time] failed (bad_judgment): Reminder set for the wrong absolute time (7/13 11:07 AM instead of 4:55 PM today), so the core task of computing the relative due_time failed.
- `timer-sous-vide` [reminders-time] failed (hallucination): Reply claims 7h2m remaining, inconsistent with the expected 35 minutes from a 4:50 PM clock — a fabricated calculation unsupported by the tool trace.
- `tone-group-brevity` [tone-format] failed (missed_tool): Instead of giving the short walk/UV answer, it never called get_weather and deflected with questions, ignoring the ask.
- `tone-no-error-leak` [tone-format] partial (missed_tool): No internal error text leaked, but the reply never attempted the lookup or delivered the expected graceful 'can't get air-quality data right now' message, instead stalling with a clarifying question.
- `tone-no-filler-confirm` [tone-format] failed (bad_judgment): The tool trace shows tummy time was already logged, but the reply gives no confirmation and instead asks a question, implying the log hasn't happened yet.

### claude-sonnet-5
- `baby-digest-slash` [baby-logging] failed (bad_judgment): Slash command required a digest reply but HAL stayed silent despite fetching stats.
- `baby-log-correction` [baby-logging] partial (hallucination): Correctly undid and relogged wake at 9:30 with confirmation, but claimed a wind-down reminder was set for 11:30 AM with no such tool call in the trace.
- `baby-log-feed-terse` [baby-logging] partial (bad_judgment): Confirmation is appropriately terse, but the tool logged 02:15 (AM) instead of 2:15 PM, and the reply appends an unexplained card URL beyond the expected brief confirmation.
- `baby-log-multi-event` [baby-logging] failed (bad_judgment): Instead of acknowledging both logged events, HAL asked an unnecessary question ('what's the baby's name?') and claimed it hadn't logged yet — contradicting the tool trace, which also used AM times instead of the evening PM times.
- `baby-log-no-phantom-claim` [baby-logging] failed (hallucination): Feed was logged via the tool, but the reply fabricates a 'bottle prep reminder set for 12:56 PM' with no reminder tool call in the trace, plus an unexplained link.
- `baby-log-wake-confirm` [baby-logging] partial (bad_judgment): The wake was logged and the reply stayed on-topic, but it never explicitly confirms the log (time, catnap length) as required — just a vague 'Up and at it' plus a card link.
- `countdown-not-started-yet` [reminders-time] partial (bad_judgment): Avoided the 'already started' failure and didn't fabricate, but never did the countdown math (~54 min to 5 PM) and instead asked a clarifying question the situation didn't require.
- `errand-booking-handoff` [multi-tool-errands] partial (bad_judgment): Provided the direct booking link and clear handoff, but omitted the playbook-required offer to set a reminder/calendar note.
- `errand-fuzzy-place-reference` [multi-tool-errands] partial (bad_judgment): Avoided the wrong 'Cafeteria restaurant' fixation but punted with a clarifying question instead of interpreting the reference as the food hall near 11th Ave and offering nearby World Cup venues.
- `errand-open-day-plan` [multi-tool-errands] partial (infra_error): Tool trace returned empty baby data, so the reply honestly declined to fabricate a rhythm and still gave useful weather/UV guidance, but the core nap-aware plan was not delivered and it asked multiple follow-up questions instead.
- `errand-restaurant-find` [multi-tool-errands] failed (hallucination): The places tool returned no visible data, yet the reply asserts specific restaurants, addresses, opening hours, and distances — fabricated details the fixture doesn't support.
- `errand-sports-today` [multi-tool-errands] failed (hallucination): Expected answer was yes — Argentina vs Netherlands tonight at 9 PM ET — but the reply said no match today, contradicting the expected data and hedging with 'typically slated'.
- `errand-typo-train` [multi-tool-errands] partial (hallucination): Correctly read 'Trillin' as 'train' and gave the expected transit answer, but appended a driving time/distance not supported by any tool call in the trace.
- `factcheck-captcha-fallback` [fact-check-links] failed (missed_tool): Stopped at the captcha and asked the user to describe the video instead of falling back to web_search on the topic, explicitly violating the playbook rule.
- `group-capture-ambient-answer` [group-restraint] partial (missed_tool): Correctly interpreted '310' as 3:10pm and confirmed, but no memory/reminder tool call in the trace to persist it, and added an unnecessary question instead.
- `group-direct-ask-must-answer` [group-restraint] failed (missed_tool): It replied but deflected with a location question instead of calling places to give nearest open pharmacy options — exactly the deflection the test targets.
- `group-energy-match` [group-restraint] failed (hallucination): The places tool returned no results in the trace, yet the reply asserts specific venues, addresses, and quietness details — fabricated content; also uses two emoji against the low-key register spec.
- `group-humans-converging` [group-restraint] failed (bad_judgment): HAL replied with an unnecessary confirmation when silence was required; humans had already converged unaddressed to HAL.
- `group-respect-stfu` [group-restraint] failed (bad_judgment): HAL replied after being muted when silence was required; even acknowledging the mute violates the stfu directive.
- `heartbeat-delivery-landed` [proactive-judgment] failed (bad_judgment): Stayed silent when a package-delivered heads-up was required — the one always-surface case.
- `heartbeat-rain-window-alert` [proactive-judgment] failed (bad_judgment): Stayed silent when a concise rain alert was required, and made no tool calls to check the forecast.
- `heartbeat-security-email-caution` [proactive-judgment] failed (bad_judgment): HAL stayed silent when it needed to surface the security alert with a verify-independently caution.
- `leaveby-travel-math` [reminders-time] failed (missed_tool): Never called the travel-time tool or gave a leave-by estimate; instead asked the user for details the fixture would have provided, missing the entire ask.
- `memory-date-resolution` [memory-recall] partial (bad_judgment): The reply resolves the date but frames July 8 as already past ('should've landed already') instead of recognizing it's arriving today, missing the today-awareness the situation required.
- `memory-recall-list` [memory-recall] failed (infra_error): Reply recalled none of the four stored items; both memory tools returned empty and the response degraded to 'nothing saved' instead of the expected list.
- `memory-recall-rules` [memory-recall] failed (infra_error): HAL honestly avoided fabricating, but the seeded rules were never surfaced — all four recall attempts returned empty and the user got none of the expected information.
- `memory-recall-simple` [memory-recall] partial (hallucination): Correctly answered 'Blue' in one line, but the memory recall returned nothing in the trace, so the 'you mentioned it back in February' detail is unsupported.
- `memory-store-standing-rule` [memory-recall] partial (bad_judgment): A configure call was made (a durable mechanism), but instead of confirming the standing rule in one line, the reply asks an unnecessary question and defers the setup it apparently already did.
- `memory-update-contradiction` [memory-recall] partial (missed_tool): A write did occur (profile append) and the reply confirmed briefly, but it used the wrong tool — the expected memory update was never called — and appending 'green' leaves the stale 'blue' fact unresolved.
- `reminder-actually-created` [reminders-time] failed (bad_judgment): Reminder was created with the wrong date (7/14 vs the asserted 7/08), and instead of acknowledging the 8-10 guest count answer, it misread it as a confusing reminder request — both a hard-assertion miss and a dropped answer the rubric explicitly calls a fail.
- `reminder-relative-45min` [reminders-time] failed (bad_judgment): Reminder set for the wrong date and time (11:02 AM on 7/13 instead of 4:55 PM today), so the relative time computation was wrong.
- `timer-sous-vide` [reminders-time] failed (hallucination): Reply claims ~7h8m remaining, which contradicts the frozen 4:50 PM clock (correct answer was 35 minutes).
- `tone-group-brevity` [tone-format] failed (verbosity): The situation explicitly requires ≤3 short lines in a group; the reply is two paragraphs plus an unnecessary setup question, failing the format even though the weather/UV substance is right.
- `tone-no-error-leak` [tone-format] failed (bad_judgment): Reply leaks internal error details ('search tools are getting rate-limited/blocked'), which the expected behavior explicitly forbids.
- `tone-no-filler-confirm` [tone-format] failed (bad_judgment): Instead of a brief log confirmation, HAL asked a setup question unsupported by the tool trace, ignoring the expected acknowledgment.

### claude-haiku-4-5
- `baby-digest-slash` [baby-logging] failed (bad_judgment): No digest produced: the seeded data (4 feeds, 2 naps, 7:05 PM bedtime) was not enumerated; reply claims nothing was logged today and even leads with the forbidden '...'.
- `baby-log-ambiguous-505` [baby-logging] failed (bad_judgment): The trace shows it guess-logged a 5:05 PM feed before confirming — the exact failure being tested — and the reply falsely implies nothing was logged yet ('Let me know and I'll log it').
- `baby-log-correction` [baby-logging] partial (hallucination): Correctly undid and relogged the 9:30 wake, but claimed a wind-down reminder was set with no reminder tool call in the trace.
- `baby-log-feed-terse` [baby-logging] failed (hallucination): Never confirms the 2:15 PM 4oz feed was logged, and fabricates a 'bottle prep reminder set' with no supporting tool call.
- `baby-log-multi-event` [baby-logging] failed (bad_judgment): Reply ignored the update entirely and asked an irrelevant setup question instead of acknowledging both events; logged times were also AM instead of PM.
- `baby-log-no-phantom-claim` [baby-logging] partial (hallucination): The feed was correctly logged via the baby tool and confirmed briefly, but the reply also claims 'Bottle prep set for 12:56 PM' with no supporting tool call in the trace — a fabricated secondary action.
- `baby-log-wake-confirm` [baby-logging] partial (hallucination): Log confirmation is explicit and first as required, but the specific feed/nap times (12:45 PM, 2:15 PM) aren't supported by the tool trace and it omits the wake time/catnap detail.
- `countdown-not-started-yet` [reminders-time] failed (bad_judgment): Instead of computing the ~54-minute countdown to the 5 PM event, HAL asked an unnecessary clarifying question and never answered the ask.
- `errand-booking-handoff` [multi-tool-errands] partial (bad_judgment): Provided the booking link and clear next step, but omitted the offer to set a reminder/calendar note required by the playbook.
- `errand-fuzzy-place-reference` [multi-tool-errands] failed (bad_judgment): Instead of interpreting the fuzzy reference and answering with nearby venue evidence, it punted with clarifying questions and even second-guessed the World Cup premise, providing no help.
- `errand-open-day-plan` [multi-tool-errands] failed (bad_judgment): Instead of delivering the concrete nap/feed/weather-threaded plan, it withheld the plan and asked multiple clarifying questions — including 'where do you live' despite already pulling New York weather from the tools.
- `errand-restaurant-find` [multi-tool-errands] failed (hallucination): The places tool returned no visible results, yet the reply asserts specific restaurants, addresses, and opening hours unsupported by the trace — fabricated details the rubric explicitly fails.
- `errand-sports-today` [multi-tool-errands] failed (hallucination): The reply contradicts the expected data — it claims no matches today when the sports tool data indicated Argentina vs Netherlands semifinal tonight at 9 PM ET, asserting details (semis wrapped Jul 8-9) unsupported by the trace.
- `errand-typo-train` [multi-tool-errands] partial (missed_tool): Correctly interpreted 'Trillin' as train/transit to Far Hills, but never called travel_time or gave the route/time, instead asking for the home address after the profile came back empty.
- `errand-weather-tool-down` [multi-tool-errands] failed (missed_tool): Never fell back to web_search after the weather tool errored, instead offering a generic guess and pivoting to an irrelevant question about the baby's name rather than a real forecast-based recommendation.
- `factcheck-captcha-fallback` [fact-check-links] failed (missed_tool): Punted to the user after the captcha block without attempting web_search on the topic, violating the explicit playbook fallback.
- `factcheck-icloud-note` [fact-check-links] partial (verbosity): Correctly stops after one fetch and asks for a paste, but bloats a one-line ask into three options (two of which are redundant) plus an unnecessary follow-up question.
- `factcheck-mixed-verdict` [fact-check-links] partial (bad_judgment): The body correctly nuances both halves, but the headline verdict is a blanket '❌ Not real' instead of MIXED, and it downplays the illness-reduction evidence (~29% RCT) as 'lacks solid evidence' rather than acknowledging it exists but is overstated.
- `factcheck-no-fabrication` [fact-check-links] failed (hallucination): The browser call returned nothing, yet the reply never says it couldn't pull the video and confidently attributes specific content/techniques to it, fabricating details unsupported by the trace.
- `factcheck-true-claim` [fact-check-links] partial (hallucination): Correct TRUE verdict and detection year, but states the energy as '320 exajoules' (actual ~51 joules / 3.2×10^20 eV) — a badly wrong detail not supported by the trace, plus a bit bloated.
- `group-capture-ambient-answer` [group-restraint] partial (missed_tool): Correctly interpreted '310' as 3:10 PM, but no memory/reminder tool call was made to persist it, and it piled on extra questions instead of a short confirmation.
- `group-direct-ask-must-answer` [group-restraint] failed (bad_judgment): Ignored the urgent ask entirely — no pharmacy info from the places lookup, just an off-topic question about the baby's name.
- `group-energy-match` [group-restraint] partial (hallucination): Register is appropriately flat with two options, but the tool trace shows no results returned, so specific venues, addresses, and 'both are open now' are asserted with more certainty than the trace supports, plus a tacked-on question adds mild bloat.
- `group-humans-converging` [group-restraint] failed (bad_judgment): HAL replied with a recap when silence was required; humans converged themselves and HAL wasn't addressed.
- `group-respect-stfu` [group-restraint] failed (bad_judgment): HAL replied after being muted when silence was required, ironically breaking mute while explaining it's muted.
- `heartbeat-delivery-landed` [proactive-judgment] failed (bad_judgment): HAL stayed silent on a fresh package-delivered notice, the one case where a heads-up must always be surfaced.
- `heartbeat-rain-window-alert` [proactive-judgment] failed (bad_judgment): Stayed silent when a concise rain alert was required, and made no tool calls to check the forecast.
- `heartbeat-security-email-caution` [proactive-judgment] failed (bad_judgment): HAL stayed silent when it needed to surface the security alert with a verify-independently caution.
- `leaveby-travel-math` [reminders-time] failed (missed_tool): Never called the travel_time tool or produced a leave-by time; instead deflected with a question despite the expected 3:45-4:00 PM answer being computable.
- `memory-date-resolution` [memory-recall] failed (bad_judgment): Instead of recalling the stored delivery date and connecting it to today (Wednesday July 8), it deflected to a Google auth request and never answered the question.
- `memory-recall-list` [memory-recall] failed (infra_error): None of the four stored items were recalled; HAL claimed no prior discussion existed, likely because the recall_history call returned empty, degrading the reply.
- `memory-recall-rules` [memory-recall] failed (infra_error): The reply did not recall any of the seeded rules; the tool calls returned empty, and the assistant claimed no baby data exists instead of surfacing the seeded schedule.
- `memory-recall-simple` [memory-recall] failed (missed_tool): Claimed not to know a fact the situation says was stored, which the rubric explicitly marks as a failure.
- `memory-store-standing-rule` [memory-recall] partial (bad_judgment): The configure call was made per the trace, but the reply contradicts it by asking for the baby's name and implying setup hasn't happened, failing to confirm the standing behavior.
- `memory-update-contradiction` [memory-recall] partial (missed_tool): The preference was persisted and confirmed briefly, but via the profile tool instead of the expected memory tool, and the reply didn't acknowledge the change from blue.
- `reminder-actually-created` [reminders-time] failed (bad_judgment): Reminder was created with the wrong date (2026-07-14 vs expected 07-08 per hard assertion) and the reply failed to acknowledge the 8-10 guest count, instead asking a confused question — the rubric explicitly calls dropping the guest-count answer a fail.
- `reminder-relative-45min` [reminders-time] failed (bad_judgment): Expected a reminder at 4:55 PM today; HAL created two reminders with wrong times (8:55 PM and a different day at 10:58 AM) and confirmed the wrong one, failing the mechanical assertion.
- `reminder-weekday-math` [reminders-time] failed (bad_judgment): Resolved 'Thursday' to July 17 instead of the correct July 16, a wrong-day resolution the expected behavior explicitly calls a failure.
- `stale-price-caveat` [reminders-time] partial (hallucination): Correctly labels prices as 'as of early June' and offers a fresh check, but states the final is in Mexico City (it's at MetLife Stadium, NJ), a wrong detail unsupported by the trace.
- `timer-sous-vide` [reminders-time] failed (hallucination): Claimed ~7 hours until 5:25 PM, wildly inconsistent with the frozen 4:50 PM clock; expected 35 minutes.
- `tone-group-brevity` [tone-format] partial (verbosity): The correct walk/UV advice is present, but it's buried after an unnecessary baby-profile question and exceeds the ≤3 short lines format required for group chats.
- `tone-no-error-leak` [tone-format] partial (verbosity): No raw error strings leaked and it gracefully redirects with alternatives, but it's a multi-line reply with an unnecessary follow-up question instead of the expected clean one-liner.
- `tone-no-filler-confirm` [tone-format] failed (bad_judgment): Instead of a brief confirmation of the logged tummy time, HAL asked an unnecessary question about setup, ignoring the confirmation ask entirely.


## Known caveats — baseline run 2026-07-13

1. **Absolute handled-rates are NOT comparable to prod's ~93%.** The corpus was
   deliberately mined from historical partial/failed prod turns, so it
   oversamples known-hard situations. The signal is the RANKING and the
   per-category gaps, not the absolute rate.
2. **Time-of-day scenarios are partially confounded by the harness.** Only the
   `current_time` tool is frozen; the system prompt's wall clock is not, so
   "2:15" / "in 45 min" style inputs resolved against the real run time for
   every model. 8 scenarios (baby-log-feed-terse, baby-log-multi-event,
   reminder-relative-45min, timer-sous-vide, countdown-not-started-yet,
   leaveby-travel-math, and 2 others) failed near-identically across ALL five
   models — treat those as harness work, not model signal. Fix: freeze the
   prompt clock in harness.py.
3. **Judge fixture-blindness (fixed going forward).** The first judging pass
   could not see canned tool outputs, occasionally mis-grading
   fixture-grounded replies as hallucination (e.g. errand-restaurant-find).
   judge.py now includes fixture data. A 53-case re-judge sample measured the
   bias at 4 grade changes (2 up / 2 down, net ~0), so rankings above stand.
   Full fixture-aware re-judge is pending Anthropic API credits (balance
   exhausted mid-re-judge on 2026-07-13).
4. **gpt-5.4-mini's latency (41s mean) is tool-loop grinding**, not slow
   tokens: it retries stubbed tools far more than other models (16-call loops
   on errands). Its low multi-tool-errands score (0%) reflects the same trait.
