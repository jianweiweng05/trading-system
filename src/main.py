import pytest
import asyncio
import time
import hmac
import hashlib
from unittest.mock import Mock, patch, AsyncMock
from fastapi.testclient import TestClient
from main import app, verify_signature, rate_limit_check, REQUEST_LOG

# 保持原有fixture不变
@pytest.fixture(autouse=True)
def reset_request_log():
    """每次测试后重置全局请求日志"""
    original = REQUEST_LOG.copy()
    yield
    REQUEST_LOG.clear()
    REQUEST_LOG.update(original)

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def mock_config():
    with patch('main.CONFIG') as mock:
        mock.binance_api_key = "test_key"
        mock.binance_api_secret = "test_secret"
        mock.telegram_bot_token = "test_token"
        mock.tv_webhook_secret = "test_secret"
        mock.run_mode = "TEST"
        mock.drop_pending_updates = True
        mock.polling_timeout = 10
        mock.log_level = "INFO"
        yield mock

@pytest.fixture
def mock_exchange():
    with patch('main.binance') as mock:
        mock.return_value = AsyncMock()
        mock.return_value.fetch_time = AsyncMock(return_value=int(time.time() * 1000))
        yield mock

@pytest.fixture
def mock_database():
    with patch('main.init_db') as mock, \
         patch('main.engine') as mock_engine:
        mock_engine.connect.return_value.__aenter__ = AsyncMock()
        mock_engine.connect.return_value.__aexit__ = AsyncMock()
        yield mock

@pytest.fixture
def mock_system_state():
    with patch('main.SystemState') as mock:
        mock.set_state = AsyncMock(return_value=None)
        mock.is_active = AsyncMock(return_value=True)
        mock.get_state = AsyncMock(return_value="ACTIVE")
        yield mock

@pytest.fixture
def mock_telegram_bot():
    with patch('main.ApplicationBuilder') as mock, \
         patch('main.initialize_bot') as mock_init, \
         patch('main.stop_bot_services') as mock_stop:
        mock_app = Mock()
        mock_app.updater = Mock()
        mock_app.updater.start_polling = AsyncMock()
        mock_app.updater.stop = AsyncMock()
        mock.return_value.token.return_value.build.return_value = mock_app
        yield mock_app

# 参数化测试用例
@pytest.mark.parametrize("secret, signature, payload, expected", [
    ("test_secret", "valid", b"test_payload", False),  # 无效签名
    ("test_secret", "", b"test_payload", False),       # 空签名
    ("", "any_signature", b"test_payload", True),      # 无密钥配置
])
def test_verify_signature(secret, signature, payload, expected):
    """参数化测试签名验证的各种情况"""
    # 计算有效签名
    if signature == "valid":
        signature = hmac.new(secret.encode('utf-8'), payload, hashlib.sha256).hexdigest()
        expected = True
    
    result = verify_signature(secret, signature, payload)
    assert result == expected

# 参数化频率限制测试
@pytest.mark.parametrize("requests_count, should_limit", [
    (1, False),   # 单次请求
    (19, False),  # 低于阈值
    (20, True),   # 达到阈值
    (25, True),   # 超过阈值
])
def test_rate_limit_check(requests_count, should_limit):
    """测试不同请求频率下的限流行为"""
    client_ip = "test_ip"
    
    # 模拟请求
    for i in range(requests_count):
        # 确保时间戳不同
        with patch('time.time', return_value=time.time() + i*0.01):
            result = rate_limit_check(client_ip)
    
    # 验证最后一次请求结果
    assert result == should_limit
    
    # 验证时间窗口过期
    REQUEST_LOG[client_ip] = [time.time() - 61]  # 61秒前的请求
    assert rate_limit_check(client_ip) == True
    assert len(REQUEST_LOG[client_ip]) == 1

# 生命周期测试增强
@pytest.mark.asyncio
async def test_lifespan_success(mock_config, mock_exchange, mock_database, mock_system_state, mock_telegram_bot):
    """测试正常生命周期流程"""
    async with app.router.lifespan_context(app):
        # 验证初始化
        assert app.state.exchange is not None
        assert app.state.telegram_app is not None
        
        # 验证轮询任务启动
        assert hasattr(app.state, 'polling_task')
        assert not app.state.polling_task.done()
        
        # 验证系统状态
        assert await SystemState.is_active() == True

@pytest.mark.asyncio
async def test_lifespan_failure(mock_config, mock_exchange, mock_database, mock_system_state):
    """测试启动失败时的清理流程"""
    # 模拟启动阶段失败
    with patch('main.init_config', side_effect=Exception("Test error")):
        async with app.router.lifespan_context(app):
            pass  # 生命周期应正常执行清理
    
    # 验证清理操作
    if hasattr(app.state, 'exchange'):
        assert app.state.exchange.close.called

# 参数化端点测试
@pytest.mark.parametrize("endpoint, method, expected_status", [
    ("/", "GET", 200),
    ("/health", "GET", 200),
    ("/startup-check", "GET", 200),
    ("/webhook", "POST", 401),  # 默认无签名
    ("/nonexistent", "GET", 404),
])
def test_endpoint_availability(client, endpoint, method, expected_status):
    """测试所有端点的基本可用性"""
    if method == "GET":
        response = client.get(endpoint)
    else:
        response = client.post(endpoint, json={})
    assert response.status_code == expected_status

# 增强Webhook测试
@pytest.mark.parametrize("scenario", [
    "valid",             # 有效请求
    "invalid_signature", # 无效签名
    "rate_limited",      # 频率限制
    "system_inactive",   # 系统未激活
    "no_config",         # 配置未加载
    "invalid_json",      # 无效JSON
])
@pytest.mark.asyncio
async def test_webhook_endpoint(client, mock_config, mock_system_state, scenario):
    """参数化测试Webhook各种场景"""
    headers = {"X-Tv-Signature": "test_signature"}
    payload = {"test": "data"}
    
    # 设置场景条件
    if scenario == "valid":
        with patch('main.verify_signature', return_value=True), \
             patch('main.rate_limit_check', return_value=True):
            response = client.post("/webhook", json=payload, headers=headers)
            assert response.status_code == 200
    
    elif scenario == "invalid_signature":
        response = client.post("/webhook", json=payload, headers=headers)
        assert response.status_code == 401
    
    elif scenario == "rate_limited":
        with patch('main.verify_signature', return_value=True), \
             patch('main.rate_limit_check', return_value=False):
            response = client.post("/webhook", json=payload, headers=headers)
            assert response.status_code == 429
    
    elif scenario == "system_inactive":
        mock_system_state.is_active = AsyncMock(return_value=False)
        response = client.post("/webhook", json=payload, headers=headers)
        assert response.status_code == 503
    
    elif scenario == "no_config":
        with patch('main.CONFIG', None):
            response = client.post("/webhook", json=payload, headers=headers)
            assert response.status_code == 503
    
    elif scenario == "invalid_json":
        response = client.post("/webhook", content="invalid_json", headers=headers)
        assert response.status_code == 400

# 轮询任务测试增强
@pytest.mark.asyncio
async def test_run_safe_polling_normal(mock_telegram_bot, mock_config):
    """测试轮询任务正常流程"""
    polling_task = asyncio.create_task(run_safe_polling(mock_telegram_bot))
    
    # 等待任务启动
    await asyncio.sleep(0.1)
    assert mock_telegram_bot.updater.start_polling.called
    
    # 测试正常停止
    polling_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await polling_task
    assert mock_telegram_bot.updater.stop.called

@pytest.mark.asyncio
async def test_run_safe_polling_error(mock_telegram_bot):
    """测试轮询任务异常处理"""
    mock_telegram_bot.updater.start_polling.side_effect = Exception("Test error")
    with pytest.raises(Exception):
        await run_safe_polling(mock_telegram_bot)

# 新增健康检查详细测试
@pytest.mark.asyncio
async def test_startup_check_failure_scenarios(client, mock_config):
    """测试健康检查的失败场景"""
    # 数据库连接失败
    with patch('main.engine.connect', side_effect=Exception("DB error")):
        response = client.get("/startup-check")
        assert response.json()["checks"]["db_accessible"] is False
    
    # 交易所连接失败
    with patch('main.binance', side_effect=Exception("Exchange error")):
        response = client.get("/startup-check")
        assert response.json()["checks"]["exchange_ready"] is False
    
    # 配置加载失败
    with patch('main.CONFIG', None):
        response = client.get("/startup-check")
        assert response.json()["checks"]["config_loaded"] is False

# 新增性能测试
@pytest.mark.benchmark
def test_rate_limit_performance(benchmark):
    """性能测试：验证频率检查函数的效率"""
    benchmark(rate_limit_check, "perf_test_ip")

# 新增并发测试
@pytest.mark.asyncio
async def test_concurrent_rate_limit():
    """并发测试：验证频率检查在并发场景下的行为"""
    client_ip = "concurrent_ip"
    async def make_request():
        rate_limit_check(client_ip)
    
    # 并发执行25次请求
    tasks = [asyncio.create_task(make_request()) for _ in range(25)]
    await asyncio.gather(*tasks)
    
    # 验证限流结果
    assert len(REQUEST_LOG[client_ip]) == 20
    assert rate_limit_check(client_ip) == False
