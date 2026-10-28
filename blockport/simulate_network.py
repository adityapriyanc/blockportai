#!/usr/bin/env python3
"""BlockPort AI - Multi-Node Blockchain Network Simulation.

Demonstrates three fully-independent BlockchainNode instances:
  - Port-Authority   : submits approval decisions
  - Terminal-A       : submits vessel docking records
  - Customs-Hub      : submits emissions certificates

Topology: full mesh (every node peers with every other).

Run:
    python simulate_network.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import datetime

from blockport.blockchain.ledger import (
    BlockchainNetwork,
    LedgerTransaction,
    OperatorWallet,
)


def print_section(title: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def main() -> None:
    # -- 1. Build the network ---------------------------------------------
    print_section("BLOCKPORT AI -- MULTI-NODE BLOCKCHAIN NETWORK SIMULATION")

    net = BlockchainNetwork(name="BlockPort Port-Authority P2P Network")

    net.add_node("Port-Authority")
    net.add_node("Terminal-A")
    net.add_node("Customs-Hub")

    # Full mesh: every node is a peer of every other.
    net.connect_all()

    print("\n[+] Network initialised with 3 nodes (full-mesh topology)")
    net.network_status()

    # -- 2. Port-Authority submits a berth approval ------------------------
    print_section("ROUND 1 -- Port-Authority broadcasts Block #1 (Berth Approval)")

    tx1, block1 = net.broadcast_tx(
        from_node_id="Port-Authority",
        record_type="APPROVE_PLAN",
        subject_table="approvals",
        subject_id=101,
        payload={
            "decision": "APPROVED",
            "assigned_berth": "B1",
            "vessel": "MV Delayed",
            "notes": "Weather clear. Terminal B logistics slots verified.",
        },
    )
    print(f"[+] Tx signed by:    {tx1.operator_address}")
    print(f"[+] Tx record_hash:  {tx1.record_hash[:24]}...")
    print(f"[+] Tx signature:    {tx1.signature[:24]}...")
    print(f"[+] Tx verify():     {tx1.verify()}")
    print(f"[+] Block #:         {block1.index}")
    print(f"[+] Block hash:      {block1.block_hash[:24]}...")

    print("\n--- Node states after broadcast ---")
    net.network_status()

    # -- 3. Terminal-A submits a docking record ----------------------------
    print_section("ROUND 2 -- Terminal-A broadcasts Block #2 (Vessel Dock)")

    tx2, block2 = net.broadcast_tx(
        from_node_id="Terminal-A",
        record_type="VESSEL_DOCK",
        subject_table="port_calls",
        subject_id=101,
        payload={
            "vessel_id": 3,
            "vessel_name": "MV Delayed",
            "berth": "B1",
            "loa_m": 300.0,
            "draft_m": 12.0,
            "cargo_units": 960,
        },
    )
    print(f"[+] Tx signed by:    {tx2.operator_address}")
    print(f"[+] Tx verify():     {tx2.verify()}")
    print(f"[+] Block hash:      {block2.block_hash[:24]}...")

    net.network_status()

    # -- 4. Customs-Hub submits emissions cert -----------------------------
    print_section("ROUND 3 -- Customs-Hub broadcasts Block #3 (Emissions Cert)")

    tx3, block3 = net.broadcast_tx(
        from_node_id="Customs-Hub",
        record_type="EMISSIONS_CERT",
        subject_table="energy_records",
        subject_id=501,
        payload={
            "vessel_id": 3,
            "co2_kg": 28416.0,
            "cargo_units": 960,
            "emissions_per_unit": 29.6,
            "anchorage_idle_hours": 0.0,
            "certified": True,
        },
    )
    print(f"[+] Tx signed by:    {tx3.operator_address}")
    print(f"[+] Tx verify():     {tx3.verify()}")
    print(f"[+] Block hash:      {block3.block_hash[:24]}...")

    net.network_status()

    # -- 5. Consensus sync -------------------------------------------------
    print_section("CONSENSUS -- sync_all() across all nodes")
    results = net.sync_all()
    for node_id, switched in results.items():
        status = "adopted longer chain" if switched else "already on longest chain"
        print(f"  {node_id}: {status}")

    all_agree = net.all_chains_agree()
    print(f"\n[+] All nodes agree on same chain tip: {all_agree}")
    net.network_status()

    # -- 6. Integrity audit across all nodes -------------------------------
    print_section("INTEGRITY AUDIT -- verify_all()")
    audit = net.verify_all()
    for node_id, (valid, msg) in audit.items():
        mark = "[PASS]" if valid else "[FAIL]"
        print(f"  {node_id}: {mark}  -- {msg}")

    # -- 7. Network event log ----------------------------------------------
    print_section("NETWORK EVENT LOG")
    for line in net.network_log():
        print(" ", line)

    # -- 8. Block-by-block inspection of one node --------------------------
    print_section("BLOCK EXPLORER -- Port-Authority node (all 4 blocks)")
    pa = net["Port-Authority"]
    for blk in pa._blockchain:
        tag = "(genesis)" if blk.index == 0 else ""
        print(f"\n  Block #{blk.index} {tag}")
        print(f"    timestamp    : {blk.timestamp.isoformat()}")
        print(f"    previous_hash: {blk.previous_hash[:24]}...")
        print(f"    merkle_root  : {blk.merkle_root[:24]}...")
        print(f"    block_hash   : {blk.block_hash[:24]}...")
        print(f"    transactions : {len(blk.transactions)}")
        for tx in blk.transactions:
            print(f"      tx_hash      : {tx.tx_hash[:24]}...")
            print(f"      record_type  : {tx.record_type}")
            print(f"      operator_addr: {tx.operator_address}")
            print(f"      signature ok : {tx.verify()}")

    print("\n" + "=" * 70)
    print("  NETWORK SIMULATION COMPLETE")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
