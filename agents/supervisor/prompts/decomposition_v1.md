## Task decomposition (additional output field)

Also return tasks: an array of at most six objects with id (unique string),
agent (price or policy), question (focused subquestion), and required_elements
(nonempty array of requested answer elements). Keep the original four fields.

Use one task for a simple question. Split requests that need different agents
or independently retrieved facts. Keep related policy conditions together.
Cover every requested part that the selected sources could address. Preserve
towns, flat types, dates, comparisons, relevant user conditions and claims to
check. Never turn a user's unverified premise into an established fact. Do not
invent constraints or silently replace an unsupported request with another one.
Rules R1-R5 still apply, including the restriction on personal financial figures.
R6 also applies: omit unrelated requests from task questions and required
elements. For mixed requests, create tasks only for the supported housing
parts and identify the unsupported parts in the routing reason. Preserve
all conditions relevant to those housing parts. Entirely unrelated requests
have route "none" and an empty tasks array.

Price tasks ask only for historical resale transaction statistics or context.
Policy tasks ask only for rules, procedures or eligibility, without asking the
policy source to supply historical price statistics. Preserve any connection
needed to interpret the policy (for example that the purchase is resale).
The price agent looks up one town, one flat type and one period per task.
For a comparison across towns, flat types or periods, create one price task
per town, flat type or period being compared (for example, Tampines vs Bishan
4-room flats: one task for Tampines 4-room, one for Bishan 4-room); never put
two towns in one price task. Do not ask an agent to produce a statistic its
interface cannot supply, such as a difference or ranking; synthesis compares
the separate results.

For the geographic price proxy allowed by R8, preserve the requested
location and explicitly name the supported containing/nearby town in the
price task. State the location basis instead of silently changing the place.
Required elements must include the proxy town, requested flat type and
period, transaction count and an explicit approximate-area disclosure.
Do not invent a nearby town, a distance or an exact-address price. If the
location relationship is unknown, retain that limitation rather than
creating a guessed price task. An exact-price request remains unanswerable
when only area-level context can be supplied.

The set of task agents must match route: price -> price only; policy -> policy
only; both -> at least one of each; none -> empty tasks. For an unanswerable
question, retain the original question and limitations in the routing reason;
tasks may request relevant context allowed by R1-R5 but must not pretend to
answer the unsupported main request. Required elements describe the requested
facts; they are not guesses about what the evidence will say.

Example: "What was the average price of Tampines 4-room resale flats in 2023,
and which grants can first-time couples receive?" has two tasks:
{"id":"price_1","agent":"price","question":"What was the average resale price of Tampines 4-room flats from January to December 2023?","required_elements":["Average resale price","Matching transaction count"]}
{"id":"policy_1","agent":"policy","question":"Which grants can first-time couples receive for an HDB resale purchase, and what conditions apply?","required_elements":["Applicable grants","Eligibility conditions"]}
