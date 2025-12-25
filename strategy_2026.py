import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

# --- 0. 页面配置 (必须是第一行代码) ---
st.set_page_config(page_title="2026 逐星计划", layout="wide")

# --- 1. 定义投资组合 (使用你提供的最新标的) ---
PORTFOLIOS = {
    "AI全产业": ["MAGS", "VRT", "GRID", "SRVR", "URA", "SMH"], 
    "SpaceX概念": ["RKLB", "ARKX", "STM"], 
    "HI3基石": ["VNQ", "PFF", "MOAT"], 
    "Elon概念": ["TSLA", "XPEV"] 
}
# 策略基准时间
START_DATE = "2025-01-01" 

# --- 2. 核心数据函数 (带缓存，提速) ---
@st.cache_data(ttl=3600)
def fetch_all_data(portfolios, start_date):
    """
    一次性下载所有数据，并处理未来日期逻辑
    """
    all_tickers = list(set(t for tickers in portfolios.values() for t in tickers))
    
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    today = datetime.now()
    is_future = start_dt > today
    
    # 如果是未来日期，自动回溯60天作为预览数据
    fetch_start = start_date if not is_future else (today - pd.Timedelta(days=60)).strftime("%Y-%m-%d")
    
    try:
        # group_by='ticker' 方便后续按股票提取
        data = yf.download(all_tickers, start=fetch_start, progress=False, group_by='ticker')
    except Exception as e:
        st.error(f"数据下载异常: {e}")
        return pd.DataFrame(), False
        
    return data, is_future

def get_portfolio_nav(data, tickers, start_date, is_future):
    """
    计算指定组合的净值曲线
    """
    if not tickers or data.empty: return None, None
    
    closes = pd.DataFrame()
    
    # 提取收盘价
    for t in tickers:
        try:
            # 兼容 yfinance 多层索引结构
            if isinstance(data.columns, pd.MultiIndex):
                if t in data:
                    closes[t] = data[t]['Close']
            else:
                closes[t] = data['Close'] # 单只股票情况
        except KeyError:
            continue
            
    # 清洗空数据
    valid_data = closes.dropna(how='all')
    if valid_data.empty: return None, None
    
    # 确定基准点 (Cost Basis)
    if is_future:
        # 预览模式：以第一天收盘价为基准
        base_date = valid_data.index[0]
    else:
        # 实盘模式：寻找 >= start_date 的最近交易日
        start_ts = pd.to_datetime(start_date).tz_localize(valid_data.index.dtype.tz) if valid_data.index.tz else pd.to_datetime(start_date)
        future_data = valid_data[valid_data.index >= start_ts]
        if future_data.empty: return None, None
        base_date = future_data.index[0]

    # 以基准日价格作为成本 (归一化为 1.0)
    cost_basis = valid_data.loc[base_date]
    
    # 计算个股净值 (今日股价 / 基准日股价)
    stock_navs = valid_data.loc[base_date:].div(cost_basis)
    
    # 计算组合净值 (假设等权重)
    portfolio_nav = stock_navs.mean(axis=1)
    
    return portfolio_nav, stock_navs

# --- 3. 业务逻辑处理 ---

# A. 准备数据
with st.spinner("🛰️ 正在连接星链获取实时数据..."):
    full_data, is_future_mode = fetch_all_data(PORTFOLIOS, START_DATE)

all_navs = pd.DataFrame() # 存所有组合净值
details_map = {} # 存个股详情

if not full_data.empty:
    for name, tickers in PORTFOLIOS.items():
        p_nav, s_navs = get_portfolio_nav(full_data, tickers, START_DATE, is_future_mode)
        if p_nav is not None:
            all_navs[name] = p_nav
            # 获取最新价格用于展示
            latest_prices = full_data.xs('Close', level=1, axis=1).iloc[-1] if isinstance(full_data.columns, pd.MultiIndex) else full_data['Close'].iloc[-1]
            details_map[name] = {"stock_navs": s_navs, "latest_prices": latest_prices}

    # 计算总策略净值
    if not all_navs.empty:
        all_navs['总策略'] = all_navs.mean(axis=1)

# --- 4. 界面渲染 (核心修改区域) ---

st.title("🚀 2026 逐星计划 (Starship 2026)")
if is_future_mode:
    st.info(f"⏳ **预览模式**：策略将于 {START_DATE} 正式启动，当前展示最近模拟走势。")

# ========== 🔴 核心修改：置顶仪表盘 (Top Dashboard) ==========
if not all_navs.empty:
    # 1. 提取关键指标
    latest_nav = all_navs['总策略'].iloc[-1]
    prev_nav = all_navs['总策略'].iloc[-2] if len(all_navs) > 1 else latest_nav
    
    # 计算涨跌
    daily_change = (latest_nav - prev_nav) / prev_nav
    total_return = (latest_nav - 1.0)
    
    latest_date_str = all_navs.index[-1].strftime("%Y-%m-%d")

    # 2. 绘制顶部容器 (Container)
    with st.container():
        st.markdown("### 🏆 账户总览")
        
        # A. 关键数字 (Metrics)
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("总净值 (Net Value)", f"{latest_nav:.4f}", help="初始净值为 1.0000")
        m2.metric("今日涨跌 (Daily)", f"{daily_change:.2%}", delta_color="normal")
        m3.metric("累计收益 (Total)", f"{total_return:.2%}", delta_color="normal")
        m4.metric("📅 数据日期", latest_date_str)
        
        # B. 账户总净值趋势大图 (Big Chart)
        # 放在这里，确保它在子组合之前显示
        fig = go.Figure()
        
        # 先画子策略（灰色虚线，作为背景参考）
        for col in all_navs.columns:
            if col != '总策略':
                fig.add_trace(go.Scatter(
                    x=all_navs.index, y=all_navs[col], name=col,
                    line=dict(width=1, dash='dot'), opacity=0.5
                ))
        
        # 再画总策略（红色粗线，醒目）
        fig.add_trace(go.Scatter(
            x=all_navs.index, y=all_navs['总策略'], name='🔥 总策略',
            line=dict(width=3, color='#FF4B4B') # 红色
        ))
        
        fig.update_layout(
            height=350,
            margin=dict(l=0, r=0, t=10, b=0),
            hovermode="x unified",
            yaxis_title="净值",
            legend=dict(orientation="h", y=1.1, x=0.5, xanchor="center") # 图例放上面
        )
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("---") # 分割线

# ========== 🟢 模块二：子组合详情 (Grid Layout) ==========
st.subheader("🧩 四大引擎详细表现")

cols = st.columns(2)
for i, (name, tickers) in enumerate(PORTFOLIOS.items()):
    if name in all_navs.columns:
        # 获取数据
        series = all_navs[name]
        curr = series.iloc[-1]
        ret = (curr - 1.0) * 100
        
        with cols[i % 2]:
            st.markdown(f"#### {name}")
            st.metric("组合净值", f"{curr:.4f}", f"{ret:.2f}%")
            
            # 绘制小图
            st.line_chart(series, height=200, color="#2980b9")
            
            # 买入详情折叠面板
            with st.expander(f"📋 {name} - 持仓与贡献"):
                st.caption(f"包含标的: {', '.join(tickers)}")
                st.caption("策略：每月1日买入，等权分配。")
                
                # 制作详情表格
                if name in details_map:
                    d = details_map[name]
                    s_navs = d['stock_navs']
                    prices = d['latest_prices']
                    
                    # 获取每只股票的累计贡献 (Current Nav)
                    current_stock_navs = s_navs.iloc[-1]
                    
                    # 组装表格
                    df_detail = pd.DataFrame({
                        "股票": current_stock_navs.index,
                        "累计净值贡献": current_stock_navs.values,
                        "最新市价($)": [prices.get(t, 0) for t in current_stock_navs.index]
                    })
                    # 格式化并展示
                    st.dataframe(
                        df_detail.set_index("股票").style.format("{:.2f}"),
                        use_container_width=True
                    )
