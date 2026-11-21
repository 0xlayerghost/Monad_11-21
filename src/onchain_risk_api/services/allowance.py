from datetime import UTC, datetime
from hashlib import sha256

from onchain_risk_api.core.config import Settings
from onchain_risk_api.domain.allowance import allowance_identity
from onchain_risk_api.domain.errors import (
    BlockNotFoundError,
    NetworkNotConfiguredError,
    SnapshotChangedError,
    SpenderNotConfiguredError,
    TokenNotConfiguredError,
)
from onchain_risk_api.domain.models import Erc20AllowanceEvidence, Erc20AllowanceResponse
from onchain_risk_api.providers.base import ChainProvider
from onchain_risk_api.rules.allowance import evaluate_allowance_rules
from onchain_risk_api.services.network import NetworkService


# 业务编排层：校验查询范围、协调链上读取、生成证据并运行规则；不签名或发送交易。
# class 类似 contract 的定义；AllowanceService(...) 创建内存对象，不部署链上实例。
class AllowanceService:
    # __init__ 类似构造函数，但只初始化链下对象，不会部署合约。
    # self 是当前实例；* 表示后面的参数必须用 settings=...、provider=... 传入。
    def __init__(self, *, settings: Settings, provider: ChainProvider) -> None:
        # provider 按 ChainProvider 接口提供读取能力，具体 RPC 细节交给实现类。
        # 类似保存接口类型的依赖：self._provider 引用传入的对象，并非继承了它的方法。
        # 正常启动传入 Web3RpcProvider，其类实现了下面调用的 get_erc20_allowance。
        # 单下划线表示约定的内部属性，不是 Solidity private 那样的访问控制。
        self._settings = settings
        self._provider = provider
        self._network = NetworkService(settings=settings, provider=provider)
        # 集合推导式：统一小写并去重，便于白名单匹配；不是修改链上的地址或授权。
        self._tokens = {address.lower() for address in settings.erc20_allowed_tokens}
        self._spenders = {address.lower() for address in settings.erc20_allowed_spenders}

    # async/await 用于等待网络 I/O；不是后台自动执行，调用方也需要 await 此方法。
    # str | None、int | None 表示可选类型；类型标注本身不负责运行时校验。
    # HTTP 入口会校验地址和非负区块号；返回类型是响应模型，不是链上交易。
    async def get_allowance(
        self,
        token_address: str,
        owner_address: str,
        spender_address: str,
        *,
        network_name: str | None = None,
        block_number: int | None = None,
    ) -> Erc20AllowanceResponse:
        # 1. 先检查网络名及 token/spender 白名单，拒绝后不继续请求 RPC。
        # token 名单为空时允许任意合法 token；spender 名单为空时仍拒绝全部 spender。
        # 两个名单允许任意组合，不是一一配对；owner 由请求传入，不在此处设白名单。
        if network_name is not None and network_name != self._settings.network_name:
            raise NetworkNotConfiguredError()
        if self._tokens and token_address.lower() not in self._tokens:
            raise TokenNotConfiguredError()
        if spender_address.lower() not in self._spenders:
            raise SpenderNotConfiguredError()
        # 2. 读取 RPC 的实际 chain ID 并核对配置，不能只相信路径中的网络名。
        network = await self._network.get_status(network_name=network_name)
        # 3. 先选区块，再按固定高度读取；is not None 保证区块 0 不会被当成 latest。
        block_identifier = block_number if block_number is not None else "latest"
        block = await self._provider.get_block(block_identifier)
        # 对应 IERC20(token).allowance(owner, spender)，由 provider 执行只读 eth_call。
        # amount 是最小单位整数，不做 decimals 换算；读取失败会抛错，不回退为零。
        amount = await self._provider.get_erc20_allowance(
            token_address, owner_address, spender_address, block_number=block.number
        )
        # 4. 复核同高度的区块 hash；区块消失或变化时丢弃本次读取。
        # 这只能检查部分重组情况，不是原子快照，也不保证最终性。
        try:
            confirmed = await self._provider.get_block(block.number)
        except BlockNotFoundError as exc:
            # raise ... from exc 转换业务错误，同时保留原始异常作为原因。
            raise SnapshotChangedError() from exc
        if confirmed.block_hash != block.block_hash:
            raise SnapshotChangedError()
        # 5. 将链、区块、三方地址和额度按固定顺序拼接，作为版本化证据的摘要输入。
        # 类似 Solidity 中先 abi.encode(...)，再对编码结果取 hash 生成记录 ID 的思路。
        # 这里只是思路类似：实际使用冒号分隔文本，不是 ABI 编码，不能直接互换摘要。
        # ":".join(["a", "b", "c"]) 得到 "a:b:c"；identity 此时只是字符串，还不是 hash。
        # str(...) 将整数转成十进制文本；lower() 统一十六进制文本大小写，不改变地址值。
        # 字段含义依次为：
        # - erc20-allowance：证据类型标签，区分其他查询；类似哈希输入的域标签。
        # - v1：摘要格式版本，避免未来修改格式时混淆旧 ID；不是 token 合约版本。
        # - chain_id：类似 block.chainid，但来自已核验的 RPC 网络身份。
        # - block.number / block_hash：目标快照的高度与 hash，不一定是当前链头。
        # - token / owner / spender：哪个代币、谁的授权、授权给谁；owner 不是 msg.sender。
        # - amount：该快照的 allowance 最小单位整数，不是转账金额，也不是余额。
        # 区块 hash 让同高度的不同区块产生不同摘要输入，额度也绑定进该记录。
        # 固定字段顺序是 ID 格式的一部分；调整顺序或格式需要考虑版本与兼容性。
        # 所有这些字段相同时输入相同；观测时间和 provider 标签不参与，重复查询 ID 稳定。
        # 当前字段经约束不含冒号；若未来加入自由文本，需重新设计无歧义的编码方式。
        identity = allowance_identity(
            chain_id=network.chain_id,
            block_number=block.number,
            block_hash=block.block_hash,
            token_address=token_address,
            owner_address=owner_address,
            spender_address=spender_address,
            allowance_smallest_unit=str(amount),
        )
        # 6. 创建证据数据对象，类似填充 struct；Pydantic 会按模型约束校验字段。
        # identity.encode() 转 UTF-8 字节；sha256(...) 取摘要；hexdigest() 转 64 位十六进制文本。
        # Solidity 也有 sha256(bytes)，但这里不是常见的 keccak256，也没有使用 abi.encode。
        # evidence: 是可读的类型前缀，不参与本行 SHA-256 计算；完整结果是证据 ID。
        # SHA-256 摘要只标识内容，不是签名，也不能证明 RPC 返回内容真实无误。
        evidence = Erc20AllowanceEvidence(
            evidence_id="evidence:" + sha256(identity.encode()).hexdigest(),
            network=network.network,
            chain_id=network.chain_id,
            provider=network.provider,
            token_address=token_address,
            owner_address=owner_address,
            spender_address=spender_address,
            # uint256 以十进制字符串返回，避免前端将其当作普通 JSON 数字时丢失精度。
            allowance_smallest_unit=str(amount),
            block_number=block.number,
            block_hash=block.block_hash,
            block_timestamp=block.timestamp,
            # observed_at 是后端本次观测时间；block_timestamp 是链上区块时间。
            observed_at=datetime.now(UTC),
        )
        # 7. 返回事实证据、规则关注项与覆盖限制，不调用 LLM 推断额度或风险。
        return Erc20AllowanceResponse(
            evidence=evidence,
            # 仅精确等于 2**256 - 1 时提示最大授权；关注项不等于恶意判定。
            findings=evaluate_allowance_rules(evidence),
            # 没有枚举历史或其他授权；零不证明曾撤销，空 findings 也不代表安全。
            limitations=[
                "Only the requested token/owner and configured spender at the selected block "
                "were read.",
                "No approval history or other allowances were enumerated; "
                "zero is not proof of revocation.",
                "No token metadata, transferability, spender identity or finality was verified.",
                "An empty findings list is not a safety assessment; "
                "only exact max uint256 and finite non-zero allowances are flagged.",
                "Block-number reads with a hash recheck are not an atomic snapshot "
                "or a finality guarantee.",
            ],
        )
