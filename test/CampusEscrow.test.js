const { expect } = require("chai");
const { ethers } = require("hardhat");

/**
 * TDD GREEN 阶段 — 合约已编译，测试应对齐接口:
 *   - createOrder 前需要 registerWhitelist(proof) (卖家)
 *   - fundOrder 仅买家可调用
 *   - 错误消息与合约 modifier 一致
 *
 * 预计算 Merkle 数据 (5 个 Hardhat 默认 Signers, nonce=0):
 *   由 scripts/merkle_gen.py 生成，算法源自 mybitcoin/src/Core/Merkle.cpp
 */
const MERKLE_ROOT =
  "0x5a7230044507795a5a0fce660cff3d8e1e9b7c453e204c98167df44beb42da4b";

// 索引 0: 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266 (buyer)
const VALID_PROOF_0 = [
  "0x14e04a66bf74771820a7400ff6cf065175b3d7eb25805a5bd1633b161af5d101",
  "0xc48f43bce9db2e282f17d9c6e7c3b332805381b61d3cd81ac0262c620fea88b9",
  "0x3ee398e9ddf929f28ddf17b926f86fb103c8e02003f656fc91905c20f5b1af42",
];

// 索引 1: 0x70997970C51812dc3A010C7d01b50e0d17dc79C8
const VALID_PROOF_1 = [
  "0x723077b8a1b173adc35e5f0e7e3662fd1208212cb629f9c128551ea7168da722",
  "0xc48f43bce9db2e282f17d9c6e7c3b332805381b61d3cd81ac0262c620fea88b9",
  "0x3ee398e9ddf929f28ddf17b926f86fb103c8e02003f656fc91905c20f5b1af42",
];

// 索引 2: 0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC (seller)
const VALID_PROOF_2 = [
  "0x6d1035fce6503985ab075a4ff3f7ce2e57cd5a9c5e6a0589dccacfea7bcb0af4",
  "0x55034af2fb36f4cae060757323652e659e3be1efd9eeb339480257284f07d55c",
  "0x3ee398e9ddf929f28ddf17b926f86fb103c8e02003f656fc91905c20f5b1af42",
];

// ─── 辅助 ──────────────────────────────────────────────────────
function forgeProof(proof) {
  const forged = [...proof];
  forged[0] = ethers.keccak256(ethers.toUtf8Bytes("FAKE_HASH"));
  return forged;
}

function buildLeaf(address, nonce) {
  return ethers.keccak256(
    ethers.AbiCoder.defaultAbiCoder().encode(
      ["address", "uint256"],
      [address, nonce]
    )
  );
}

// ==============================================================
// Suite A: MerkleWhitelist
// ==============================================================
describe("MerkleWhitelist", function () {
  let whitelist;
  let owner;
  let addr1;
  let addr2;

  beforeEach(async function () {
    [owner, addr1, addr2] = await ethers.getSigners();
    const Whitelist = await ethers.getContractFactory("MerkleWhitelist");
    whitelist = await Whitelist.deploy();
    await whitelist.setMerkleRoot(MERKLE_ROOT);
  });

  it("A.1 should verify a valid merkle proof for whitelisted address", async function () {
    const leaf = buildLeaf(addr2.address, 0);
    const isValid = await whitelist.verify(VALID_PROOF_2, leaf);
    expect(isValid).to.equal(true);
  });

  it("A.2 should revert for forged/invalid merkle proof", async function () {
    const forgedProof = forgeProof(VALID_PROOF_2);
    const leaf = buildLeaf(addr2.address, 0);
    await expect(whitelist.verify(forgedProof, leaf)).to.be.revertedWith(
      "Invalid proof"
    );
  });

  it("A.3 should prevent double-use of the same leaf (replay protection)", async function () {
    const leaf = buildLeaf(addr2.address, 0);
    await whitelist.verifyAndConsume(VALID_PROOF_2, leaf);
    await expect(
      whitelist.verifyAndConsume(VALID_PROOF_2, leaf)
    ).to.be.revertedWith("Leaf already used");
  });

  it("A.4 should reject address not in whitelist tree", async function () {
    const fakeLeaf = buildLeaf("0x23618e81E3f5cdF7f54C3d65f7FBc0aBf5B21E8f", 0);
    await expect(whitelist.verify(VALID_PROOF_0, fakeLeaf)).to.be.revertedWith(
      "Invalid proof"
    );
  });

  it("A.5 should reject proof with mismatched nonce", async function () {
    const leafWrongNonce = buildLeaf(addr2.address, 1);
    await expect(
      whitelist.verify(VALID_PROOF_2, leafWrongNonce)
    ).to.be.revertedWith("Invalid proof");
  });
});

// ==============================================================
// Suite B: CampusEscrow
// ==============================================================
describe("CampusEscrow", function () {
  let escrow;
  let whitelist;
  let buyer;
  let seller;
  let arbitrator1;
  let arbitrator2;
  let arbitrator3;
  let hacker;
  const PRICE = ethers.parseEther("1.0");

  // seller = signer[2] = 0x3C44CdDdB6... (VALID_PROOF_2)
  // buyer  = signer[1] = 0x70997970... (VALID_PROOF_1)
  // arbitrator1 = signer[3], arbitrator2 = signer[4], arbitrator3 = signer[5]
  // hacker = signer[6]

  beforeEach(async function () {
    const signers = await ethers.getSigners();
    buyer = signers[1];
    seller = signers[2];
    arbitrator1 = signers[3];
    arbitrator2 = signers[4];
    arbitrator3 = signers[5];
    hacker = signers[6];

    const Whitelist = await ethers.getContractFactory("MerkleWhitelist");
    whitelist = await Whitelist.deploy();
    await whitelist.setMerkleRoot(MERKLE_ROOT);

    const Escrow = await ethers.getContractFactory("CampusEscrow");
    escrow = await Escrow.deploy(whitelist.target, [
      arbitrator1.address,
      arbitrator2.address,
      arbitrator3.address,
    ]);
  });

  // ─── B.1 正向流程 ──────────────────────────────────────────────
  describe("Happy Path: CREATED → COMPLETED", function () {
    it("B.1.1 should complete full lifecycle", async function () {
      // 卖家注册白名单
      await escrow.connect(seller).registerWhitelist(VALID_PROOF_2);
      // 创建订单
      await escrow
        .connect(seller)
        .createOrder(buyer.address, PRICE, "Used MacBook Pro 2023");
      // 买家付款
      await escrow.connect(buyer).fundOrder(0, { value: PRICE });
      // 卖家发货
      await escrow.connect(seller).shipOrder(0);
      // 买家收货
      await escrow.connect(buyer).receiveOrder(0);

      const order = await escrow.orders(0);
      expect(order.state).to.equal(4); // COMPLETED
    });

    it("B.1.2 should transfer funds to seller on completion", async function () {
      await escrow.connect(seller).registerWhitelist(VALID_PROOF_2);

      const balBefore = await ethers.provider.getBalance(seller.address);
      await escrow
        .connect(seller)
        .createOrder(buyer.address, PRICE, "");
      await escrow.connect(buyer).fundOrder(0, { value: PRICE });
      await escrow.connect(seller).shipOrder(0);
      await escrow.connect(buyer).receiveOrder(0);

      const balAfter = await ethers.provider.getBalance(seller.address);
      expect(balAfter).to.be.gt(balBefore);
    });
  });

  // ─── B.2 争议路径 ──────────────────────────────────────────────
  describe("Dispute Path", function () {
    beforeEach(async function () {
      await escrow.connect(seller).registerWhitelist(VALID_PROOF_2);
      await escrow
        .connect(seller)
        .createOrder(buyer.address, PRICE, "Test Item");
      await escrow.connect(buyer).fundOrder(0, { value: PRICE });
    });

    it("B.2.1 should allow buyer to raise dispute in FUNDED state", async function () {
      await expect(
        escrow.connect(buyer).raiseDispute(0, "Item not as described")
      )
        .to.emit(escrow, "OrderDisputed")
        .withArgs(0, buyer.address);
    });

    it("B.2.2 should enter DISPUTED state after dispute raised", async function () {
      await escrow.connect(buyer).raiseDispute(0, "Damaged goods");
      const order = await escrow.orders(0);
      expect(order.state).to.equal(5); // DISPUTED
    });

    it("B.2.3 should refund buyer if 2/3 arbitrators vote for buyer", async function () {
      await escrow.connect(buyer).raiseDispute(0, "Not delivered");
      await escrow.connect(arbitrator1).voteOnDispute(0, true);
      await escrow.connect(arbitrator2).voteOnDispute(0, true);
      await escrow.connect(arbitrator1).executeArbitration(0);
      const order = await escrow.orders(0);
      expect(order.state).to.equal(4); // COMPLETED (refund)
    });
  });

  // ─── B.3 影子状态 / 权限拦截 ───────────────────────────────────
  describe("Shadow State / Access Control", function () {
    beforeEach(async function () {
      await escrow.connect(seller).registerWhitelist(VALID_PROOF_2);
      await escrow
        .connect(seller)
        .createOrder(buyer.address, PRICE, "Item");
    });

    it("B.3.1 should revert when non-buyer attempts to fund", async function () {
      await expect(
        escrow.connect(hacker).fundOrder(0, { value: PRICE })
      ).to.be.revertedWith("Only buyer");
    });

    it("B.3.2 should revert when non-seller attempts to ship", async function () {
      await escrow.connect(buyer).fundOrder(0, { value: PRICE });
      await expect(
        escrow.connect(hacker).shipOrder(0)
      ).to.be.revertedWith("Only seller");
    });

    it("B.3.3 should revert when non-buyer attempts to confirm receipt", async function () {
      await escrow.connect(buyer).fundOrder(0, { value: PRICE });
      await escrow.connect(seller).shipOrder(0);
      await expect(
        escrow.connect(hacker).receiveOrder(0)
      ).to.be.revertedWith("Only buyer");
    });

    it("B.3.4 should revert when non-arbitrator attempts to vote", async function () {
      await escrow.connect(buyer).fundOrder(0, { value: PRICE });
      await escrow.connect(buyer).raiseDispute(0, "Fake item");
      await expect(
        escrow.connect(hacker).voteOnDispute(0, true)
      ).to.be.revertedWith("Only arbitrator can vote");
    });

    it("B.3.5 should revert state transitions from wrong current state", async function () {
      // CREATED → ship → 必须 revert
      await expect(
        escrow.connect(seller).shipOrder(0)
      ).to.be.revertedWith("Invalid state transition");
    });
  });

  // ─── B.4 白名单 + 托管集成 ─────────────────────────────────────
  describe("Whitelist + Escrow Integration", function () {
    it("B.4.1 should reject createOrder if seller is not whitelisted", async function () {
      // seller 未调用 registerWhitelist → createOrder 必须 revert
      await expect(
        escrow.connect(seller).createOrder(buyer.address, PRICE, "")
      ).to.be.revertedWith("Not whitelisted");
    });

    it("B.4.2 should reject fundOrder from hacker (not the buyer)", async function () {
      await escrow.connect(seller).registerWhitelist(VALID_PROOF_2);
      await escrow
        .connect(seller)
        .createOrder(buyer.address, PRICE, "");
      await expect(
        escrow.connect(hacker).fundOrder(0, { value: PRICE })
      ).to.be.revertedWith("Only buyer");
    });
  });
});
