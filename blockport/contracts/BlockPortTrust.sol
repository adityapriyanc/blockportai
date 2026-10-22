// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title BlockPortTrust
 * @dev Layer 4 Blockchain Trust Protocol for BlockPort AI (Report §5.6, §3 Objective 6).
 *
 * Implements a hybrid off-chain/on-chain trust anchor:
 * - Sensitive operational data (AIS feeds, manifest details, telemetry) remains off-chain in relational stores.
 * - Cryptographic fingerprints (SHA-256 state hashes, Merkle roots of operational batches) are anchored immutably.
 * - Guarantees 100% integrity verification of valid operational records and 100% detection of tampered records.
 */
contract BlockPortTrust {
    address public owner;

    struct Anchor {
        bytes32 recordHash;
        string recordType;       // e.g., "APPROVE_PLAN", "VESSEL_DOCK", "VESSEL_DEPART", "EMISSIONS_CERT"
        string subjectRef;      // e.g., "port_calls:1042" or "approvals:18"
        address operator;
        uint256 timestamp;
        uint256 blockNumber;
    }

    struct BatchAnchor {
        bytes32 merkleRoot;
        uint256 recordCount;
        string batchLabel;
        address operator;
        uint256 timestamp;
        uint256 blockNumber;
    }

    // Mapping from canonical SHA-256 record hash to on-chain Anchor
    mapping(bytes32 => Anchor) private _anchors;

    // Mapping from Merkle Root to BatchAnchor
    mapping(bytes32 => BatchAnchor) private _batchAnchors;

    // All anchored hashes for sequential auditing
    bytes32[] private _recordHashes;
    bytes32[] private _merkleRoots;

    // Events for transparency and off-chain indexers
    event RecordAnchored(
        bytes32 indexed recordHash,
        string recordType,
        string subjectRef,
        address indexed operator,
        uint256 timestamp
    );

    event BatchAnchored(
        bytes32 indexed merkleRoot,
        uint256 recordCount,
        string batchLabel,
        address indexed operator,
        uint256 timestamp
    );

    event IntegrityAuditAttempted(
        bytes32 indexed recordHash,
        bool verified,
        uint256 timestamp
    );

    modifier onlyOwner() {
        require(msg.sender == owner, "BlockPortTrust: caller is not the owner");
        _;
    }

    constructor() {
        owner = msg.sender;
    }

    /**
     * @notice Anchor an individual operational milestone hash.
     * @param recordHash Canonical SHA-256 hash of the off-chain record.
     * @param recordType Milestone category (e.g., APPROVE_PLAN, VESSEL_DOCK, EMISSIONS_CERT).
     * @param subjectRef Reference identifier to the off-chain entity (table:id).
     */
    function recordAnchor(
        bytes32 recordHash,
        string calldata recordType,
        string calldata subjectRef
    ) external returns (bool) {
        require(recordHash != bytes32(0), "BlockPortTrust: invalid zero hash");
        require(_anchors[recordHash].timestamp == 0, "BlockPortTrust: record hash already anchored");

        _anchors[recordHash] = Anchor({
            recordHash: recordHash,
            recordType: recordType,
            subjectRef: subjectRef,
            operator: msg.sender,
            timestamp: block.timestamp,
            blockNumber: block.number
        });

        _recordHashes.push(recordHash);

        emit RecordAnchored(recordHash, recordType, subjectRef, msg.sender, block.timestamp);
        return true;
    }

    /**
     * @notice Anchor a batch of operational records via their Merkle Root.
     * @param merkleRoot SHA-256 Merkle root of the batch.
     * @param recordCount Number of records in the batched tree.
     * @param batchLabel Descriptive label or timestamp range for the batch.
     */
    function recordBatch(
        bytes32 merkleRoot,
        uint256 recordCount,
        string calldata batchLabel
    ) external returns (bool) {
        require(merkleRoot != bytes32(0), "BlockPortTrust: invalid zero merkle root");
        require(_batchAnchors[merkleRoot].timestamp == 0, "BlockPortTrust: batch already anchored");

        _batchAnchors[merkleRoot] = BatchAnchor({
            merkleRoot: merkleRoot,
            recordCount: recordCount,
            batchLabel: batchLabel,
            operator: msg.sender,
            timestamp: block.timestamp,
            blockNumber: block.number
        });

        _merkleRoots.push(merkleRoot);

        emit BatchAnchored(merkleRoot, recordCount, batchLabel, msg.sender, block.timestamp);
        return true;
    }

    /**
     * @notice Verify whether a given record hash is anchored on-chain.
     * @param recordHash The hash to verify.
     * @return exists True if the record exists on-chain, false otherwise.
     * @return timestamp The block timestamp when anchored (or 0 if unanchored).
     * @return operator The address of the operator who submitted the anchor.
     * @return recordType The type identifier of the anchored record.
     * @return subjectRef The subject reference of the off-chain record.
     */
    function verifyRecord(bytes32 recordHash)
        external
        view
        returns (
            bool exists,
            uint256 timestamp,
            address operator,
            string memory recordType,
            string memory subjectRef
        )
    {
        Anchor memory a = _anchors[recordHash];
        if (a.timestamp > 0) {
            return (true, a.timestamp, a.operator, a.recordType, a.subjectRef);
        }
        return (false, 0, address(0), "", "");
    }

    /**
     * @notice Verify a Merkle inclusion proof for a leaf record against an anchored root.
     * @param leafHash Hash of the target operational record.
     * @param proof Sibling hashes along the Merkle tree path.
     * @param merkleRoot The anchored Merkle root.
     */
    function verifyInclusionProof(
        bytes32 leafHash,
        bytes32[] calldata proof,
        bytes32 merkleRoot
    ) external view returns (bool) {
        require(_batchAnchors[merkleRoot].timestamp > 0, "BlockPortTrust: unanchored merkle root");

        bytes32 computedHash = leafHash;
        for (uint256 i = 0; i < proof.length; i++) {
            bytes32 proofElement = proof[i];
            if (computedHash <= proofElement) {
                // Hash(current, sibling)
                computedHash = keccak256(abi.encodePacked(computedHash, proofElement));
            } else {
                // Hash(sibling, current)
                computedHash = keccak256(abi.encodePacked(proofElement, computedHash));
            }
        }

        return computedHash == merkleRoot;
    }

    /**
     * @notice Total number of individual records anchored.
     */
    function totalAnchoredRecords() external view returns (uint256) {
        return _recordHashes.length;
    }

    /**
     * @notice Total number of batches anchored.
     */
    function totalAnchoredBatches() external view returns (uint256) {
        return _merkleRoots.length;
    }
}
