"""
backend/demo/dataset.py

Synthetic, NDA-neutral knowledge for Demo Mode: Confluence-style runbooks/KB pages
and Jira-style incidents modelled on a generic IPC/Unigy-like trading-comms platform.
No real client, site, or personal data — every identifier is a neutral placeholder.

This is the ground truth that lets the retrieval + reasoning features be built and
verified without any live Atlassian connection. Devs can extend these lists freely.
"""

from __future__ import annotations

from typing import Any, Dict, List


# --- Confluence-style runbooks / KB pages ---------------------------------
CONFLUENCE_PAGES: List[Dict[str, Any]] = [
    {
        "id": "RUNBOOK-DBPOOL",
        "space": "SRE",
        "title": "Runbook: Database connection pool exhaustion",
        "labels": ["database", "connection-pool", "timeout", "hikaricp"],
        "body": (
            "Symptoms: rising query latency, 'connection timeout' and 'pool exhausted' errors, "
            "threads BLOCKED waiting for a lease. Healthcheck shows pool-size=active with a growing "
            "wait queue. Root cause is usually connections not being released (leaked) or an undersized "
            "pool under load. Remediation: 1) inspect active vs idle connections; 2) raise maximumPoolSize "
            "and connectionTimeout only after confirming no leak; 3) add leakDetectionThreshold; 4) ensure "
            "try-with-resources around all JDBC usage; 5) restart the affected engine node to drain stuck leases."
        ),
    },
    {
        "id": "RUNBOOK-JVMHEAP",
        "space": "SRE",
        "title": "Runbook: JVM heap saturation and Full GC pauses",
        "labels": ["jvm", "gc", "heap", "memory", "g1"],
        "body": (
            "Symptoms: repeated Full GC / G1 Evacuation Pause events, heap used near max, application "
            "freezes and failovers. Root cause: heap undersized for working set, or a memory leak growing "
            "the live set. Remediation: capture a heap histogram and thread dump; compare live-set growth "
            "across dumps; raise -Xmx if working set is legitimately large; otherwise fix the leak; tune "
            "G1 (MaxGCPauseMillis) as a stopgap. Correlate GC pauses with request timeouts."
        ),
    },
    {
        "id": "RUNBOOK-DEADLOCK",
        "space": "SRE",
        "title": "Runbook: JVM thread deadlock and BLOCKED threads",
        "labels": ["jvm", "deadlock", "threads", "contention"],
        "body": (
            "Symptoms: throughput drops to zero on a subsystem, thread dump shows two or more threads "
            "each holding a lock the other needs, or many threads BLOCKED on one monitor. Root cause: "
            "lock-ordering violation or a long-held synchronized section. Remediation: identify the lock "
            "cycle in the dump; refactor to a consistent lock order or reduce critical-section scope; "
            "add timeouts to lock acquisition; restart to recover immediately."
        ),
    },
    {
        "id": "RUNBOOK-SIP5XX",
        "space": "VOICE",
        "title": "Runbook: SIP call setup failures (4xx/5xx responses)",
        "labels": ["sip", "voice", "pcap", "call-setup", "rtp"],
        "body": (
            "Symptoms: turrets/consoles fail to establish calls; PCAP shows SIP INVITE followed by 5xx "
            "(500 Server Internal Error, 503 Service Unavailable) or 4xx (403, 408 Request Timeout). "
            "Root cause: media gateway overload, codec mismatch in SDP negotiation, or registrar/proxy "
            "unavailability. Remediation: inspect the SIP response code and Reason header in the capture; "
            "for 503 check gateway capacity; for 488/606 check SDP codec offer/answer (G.711 vs G.729); "
            "verify RTP flows both directions and check jitter/packet-loss on the media path."
        ),
    },
    {
        "id": "RUNBOOK-CONFIGDRIFT",
        "space": "SRE",
        "title": "Runbook: Configuration drift and mismatch",
        "labels": ["config", "drift", "properties", "misconfiguration"],
        "body": (
            "Symptoms: a node behaves differently after deploy; features toggle unexpectedly; connection "
            "strings or pool sizes differ across nodes. Root cause: config not promoted consistently, or a "
            "manual hotfix left in place. Remediation: diff the effective config against the baseline; "
            "reconcile pool sizes, timeouts, and endpoint URLs; redeploy from source of truth; add a "
            "config-validation step to the pipeline."
        ),
    },
    {
        "id": "RUNBOOK-REPLICA-FK",
        "space": "SRE",
        "title": "Runbook: Replication foreign-key violations",
        "labels": ["database", "replication", "foreign-key", "integrity"],
        "body": (
            "Symptoms: replica inserts fail with 'violates foreign key constraint'; replica_status rows "
            "reference missing parent rows (e.g. console/device master). Root cause: out-of-order "
            "replication or a missing master insert. Remediation: ensure parent (master) rows are applied "
            "before child rows; check replication ordering and ret/backfill missing masters; add deferred "
            "constraint checking where safe."
        ),
    },
    {
        "id": "RUNBOOK-NET-TIMEOUT",
        "space": "SRE",
        "title": "Runbook: Network timeouts and upstream latency",
        "labels": ["network", "timeout", "latency", "connectivity"],
        "body": (
            "Symptoms: intermittent 'connection timeout' / 'read timed out' to an upstream service; retries "
            "succeed sometimes. Root cause: upstream saturation, packet loss, or an undersized client "
            "timeout. Remediation: measure upstream latency and error rate; check the network path for loss; "
            "add bounded retries with backoff; raise client timeouts only if the upstream is healthy."
        ),
    },
    {
        "id": "RUNBOOK-HEALTHCHECK",
        "space": "SRE",
        "title": "Runbook: Interpreting TAC HealthCheck DEGRADED reports",
        "labels": ["healthcheck", "pdf", "degraded", "diagnostics"],
        "body": (
            "The HealthCheck PDF lists subsystem checkpoints as PASSED/WARN/FAILED. A DEGRADED overall "
            "status means at least one FAILED checkpoint. Common FAILED items: connection pool saturation, "
            "disk pressure, replication lag. Cross-reference each FAILED checkpoint with the matching runbook "
            "and the live logs before acting."
        ),
    },
]


# --- Jira-style incidents / tickets ---------------------------------------
JIRA_ISSUES: List[Dict[str, Any]] = [
    {
        "id": "INC-4021",
        "project": "INC",
        "title": "Trading console timeouts during market open — DB pool exhausted",
        "status": "Resolved",
        "resolution": "Fixed",
        "labels": ["database", "connection-pool", "timeout"],
        "body": (
            "During market open, consoles saw request timeouts. HealthCheck reported pool-size=50 active=50 "
            "waiting=15. Thread dump showed SQLConnector threads BLOCKED awaiting a lease. Fix: found a JDBC "
            "leak in the sync worker (missing close), patched with try-with-resources and raised pool to 80. "
            "Post-fix latency returned to baseline."
        ),
    },
    {
        "id": "INC-4098",
        "project": "INC",
        "title": "Recurring Full GC pauses causing failovers on engine node",
        "status": "Resolved",
        "resolution": "Fixed",
        "labels": ["jvm", "gc", "heap"],
        "body": (
            "Engine node froze for 3-8s repeatedly; logs showed Full GC and G1 Evacuation Pause. Heap used "
            "was 7.6GB/8GB. Heap histograms showed a growing cache with no eviction. Fix: added an LRU bound "
            "to the cache and raised -Xmx to 12g. Full GC frequency dropped to near zero."
        ),
    },
    {
        "id": "INC-4155",
        "project": "INC",
        "title": "Calls failing with SIP 503 on voice gateway",
        "status": "Resolved",
        "resolution": "Fixed",
        "labels": ["sip", "voice", "gateway"],
        "body": (
            "Users could not establish calls; PCAP showed INVITE -> 503 Service Unavailable from the media "
            "gateway. Gateway CPU was pinned at 100%. Fix: shifted load to the secondary gateway and raised "
            "the session cap after a capacity review. Calls recovered."
        ),
    },
    {
        "id": "INC-4188",
        "project": "INC",
        "title": "Replica inserts failing: violates foreign key constraint",
        "status": "Resolved",
        "resolution": "Fixed",
        "labels": ["database", "replication", "foreign-key"],
        "body": (
            "replica_status inserts failed referencing missing console master rows. Root cause: replication "
            "applied child rows before the master backfill completed. Fix: reordered replication to apply "
            "masters first and backfilled the missing parents."
        ),
    },
    {
        "id": "INC-4210",
        "project": "INC",
        "title": "Thread deadlock stalls order-sync subsystem",
        "status": "Resolved",
        "resolution": "Fixed",
        "labels": ["jvm", "deadlock", "threads"],
        "body": (
            "Order-sync throughput dropped to zero. Thread dump showed a classic two-lock deadlock between "
            "the sync and persistence workers. Fix: enforced a single global lock order and reduced the "
            "synchronized scope; added lock-acquire timeouts."
        ),
    },
    {
        "id": "INC-4260",
        "project": "INC",
        "title": "Config drift: node using stale connection string after deploy",
        "status": "Resolved",
        "resolution": "Fixed",
        "labels": ["config", "drift"],
        "body": (
            "One node pointed at an old DB endpoint after a deploy, causing timeouts on that node only. "
            "Root cause: a manual hotfix config left in place and not promoted. Fix: redeployed config from "
            "source of truth and added a config-diff validation gate."
        ),
    },
    {
        "id": "INC-4302",
        "project": "INC",
        "title": "Intermittent upstream read timeouts to pricing service",
        "status": "Resolved",
        "resolution": "Fixed",
        "labels": ["network", "timeout", "latency"],
        "body": (
            "Intermittent 'read timed out' to the pricing upstream; retries usually succeeded. Path showed "
            "~2% packet loss on one link. Fix: network team repaired the link; added bounded retry with "
            "backoff on the client."
        ),
    },
]


def all_documents() -> List[Dict[str, Any]]:
    """Flat list used to build the demo embedding index."""
    docs = []
    for p in CONFLUENCE_PAGES:
        docs.append({**p, "_source": "demo-confluence", "_kind": "runbook"})
    for j in JIRA_ISSUES:
        docs.append({**j, "_source": "demo-jira", "_kind": "incident"})
    return docs
