# Coin-Maximization Improvement Plan

## Goal
To maximize coin yield by optimizing for the first-claim race, reliability, and fast server adaptation.

## 21 improvements

1. Create a single source of truth for all runtime state.
2. Centralize URLs, secrets, thresholds, and protocol constants in one config layer.
3. Make the websocket client the primary abstraction and keep all logic behind it.
4. Define packet schema models for join, room events, bag events, claim results, and heartbeats.
5. Log every packet with timestamp and sequence metadata for debugging.
6. Detect protocol drift automatically when server response shapes change.
7. Measure end-to-end latency at every stage of the claim flow.
8. Replace ad hoc scripts with a real worker scheduler.
9. Add health checks for each worker account and remove weak ones automatically.
10. Rotate accounts before they fail or become stale.
11. Add retry logic with smart backoff instead of blind repetition.
12. Add a rejection and cooldown system to avoid wasted attempts.
13. Turn room discovery and claiming into separate, clean phases.
14. Queue bag opportunities by value, urgency, and expected efficiency.
15. Cache recent room and bag states to avoid duplicate processing.
16. Score targets using reward value, freshness, room activity, and worker availability.
17. Use different worker tiers such as premium, fast, and fallback accounts.
18. Capture explicit failure reasons for every rejected claim.
19. Create a metrics dashboard for latency, success rate, and failure rate.
20. Keep a known-good baseline protocol script to compare against live behavior.
21. Optimize for maintainability and adaptability, since fast code changes beat slow manual fixes.

## Strategic priorities

### Phase 1: stability
- fix state management
- centralize config
- improve logging
- fix worker health tracking

### Phase 2: speed
- reduce join-to-claim latency
- use worker scheduling
- prioritize high-value bags
- rotate stale accounts

### Phase 3: resilience
- add retries and cooldowns
- detect server drift
- track failure reasons
- score opportunities intelligently

### Phase 4: scale
- use multiple worker tiers
- queue high-value tasks
- monitor throughput and win rate
- keep the system adaptive and maintainable

## Long-term mindset

The coder advantage is not brute force. It is the ability to adapt faster than the server, make the system observable, and keep the critical path simple enough to debug under pressure.
