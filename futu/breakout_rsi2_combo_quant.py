# 順勢突破 + RSI2 撈底 組合策略（富途牛牛 量化 Strategy 版）
#
# 對應 pine/breakout_rsi2_combo_strategy.pine 同 futu/breakout_rsi2_combo_mai.txt
# 2026-07 回測 (QQQ 2009-2026, 訊號收市確認下一開市價成交, 0.05% 佣金):
#   Sharpe 1.12 / CAGR 16.4% / MaxDD -21.6%  (QQQ buy-hold: Sharpe 1.00 / DD -35%)
#
# 兩個互補引擎，同一時間只持一個倉，突破優先：
#   引擎一 突破 (BO)：價格 > 前15日最高 且 MACD(5,35) DIF > 0 入場；價格 < 前20日最低 出場
#   引擎二 撈底 (MR)：空倉時 RSI(2) < 10 且 價格 > 200MA 入場；RSI(2) > 70 出場
#
# 實盤 vs 回測嘅差異（有意為之）：
#   - 回測係「收市確認訊號、下一日開市價成交」；呢度係盤中 current_price 觸發即市價成交，
#     一般入場早過回測一日，方向一致，影響輕微
#   - select=2 = 用上一根「已完成」嘅日 K 計指標，確保突破位/出場位盤中唔會郁
#
# 注意：
#   - macd_dif = MACD 快慢線差 (DIF)。你個範本生成嘅係 macd_macd (histogram)，唔係我哋
#     tune 嘅濾網。如你客戶端冇 macd_dif，喺策略編輯器函數面板搵 MACD 嘅 DIF 版本
#   - rsi / ma 兩個函數名如有出入，一樣喺函數面板對返
#   - self.持倉模式 喺策略重啟後會重置：如重啟時已有持倉，會當係突破倉（用較寬嘅20日低出場）


class Strategy(StrategyBase):

    def initialize(self):  # 初始化
        declare_strategy_type(AlgoStrategyType.SECURITY)
        self.trigger_symbols()
        self.custom_indicator()
        self.global_variables()

    def trigger_symbols(self):  # 定義驅動資產
        self.驅動標的1 = declare_trig_symbol()

    def global_variables(self):  # 定義全域變數
        # 持倉模式：'' = 空倉, 'BO' = 突破倉, 'MR' = 撈底倉
        self.持倉模式 = ''
        # 策略參數（要改喺呢度改）
        self.突破日數 = 15
        self.出場日數 = 20
        self.MACD快線 = 5
        self.MACD慢線 = 35
        self.MACD訊號 = 5
        self.RSI日數 = 2
        self.RSI買入線 = 10
        self.RSI賣出線 = 70
        self.MA日數 = 200

    def custom_indicator(self):
        self.register_indicator('MACD', '''DIF:EMA(CLOSE,SHORT)-EMA(CLOSE,LONG),COLORFF8D1E;\r\nDEA:EMA(DIF,M),COLOR0CAEE6;\r\nMACD:(DIF-DEA)*2,COLORSTICK,COLORE970DC;\r\n''', ['SHORT', 'LONG', 'M'])

    def handle_data(self):  # K線推送、Tick推送、固定時間間隔、指定時刻觸發
        qty = position_holding_qty(symbol=self.驅動標的1)

        if qty == 0:
            self.持倉模式 = ''
            self.檢查入場()
        else:
            # 重啟後模式遺失：當突破倉處理（出場較寬，較安全）
            if self.持倉模式 == '':
                self.持倉模式 = 'BO'
            self.檢查出場()

    # ---------- 入場：突破優先，其次撈底 ----------

    def 檢查入場(self):
        if self.突破入場訊號():
            if self.買到最少一手():
                self.市價全倉買入()
                self.持倉模式 = 'BO'
        elif self.撈底入場訊號():
            if self.買到最少一手():
                self.市價全倉買入()
                self.持倉模式 = 'MR'

    def 突破入場訊號(self):
        # 價格創15日新高（對上15根完成K線嘅最高） 且 MACD DIF > 0
        現價 = current_price(symbol=self.驅動標的1, price_type=THType.RTH)
        前高 = bar_custom(symbol=self.驅動標的1, data_type=BarDataType.HIGH,
                          custom_num=self.突破日數, custom_type=CustomType.K_DAY,
                          select=2, session_type=THType.RTH)
        dif = macd_dif(symbol=self.驅動標的1, fast_period=self.MACD快線,
                       slow_period=self.MACD慢線, signal_period=self.MACD訊號,
                       bar_type=BarType.K_DAY, select=2, session_type=THType.RTH)
        return 現價 > 前高 and dif > 0

    def 撈底入場訊號(self):
        # RSI(2) 超賣 且 企喺 200MA 之上（熊市唔接刀）
        現價 = current_price(symbol=self.驅動標的1, price_type=THType.RTH)
        rsi值 = rsi(symbol=self.驅動標的1, period=self.RSI日數,
                    bar_type=BarType.K_DAY, select=1, session_type=THType.RTH)
        ma值 = ma(symbol=self.驅動標的1, period=self.MA日數,
                  bar_type=BarType.K_DAY, select=1, session_type=THType.RTH)
        return rsi值 < self.RSI買入線 and 現價 > ma值

    def 買到最少一手(self):
        賣一價 = ask(symbol=self.驅動標的1, level=1)
        可買 = max_qty_to_buy_on_margin(symbol=self.驅動標的1, order_type=OrdType.MKT,
                                        price=賣一價, order_trade_session_type=TSType.RTH)
        一手 = lot_size(symbol=self.驅動標的1)
        return 可買 >= 一手

    def 市價全倉買入(self):
        賣一價 = ask(symbol=self.驅動標的1, level=1)
        可買 = max_qty_to_buy_on_margin(symbol=self.驅動標的1, order_type=OrdType.MKT,
                                        price=賣一價, order_trade_session_type=TSType.RTH)
        place_market(symbol=self.驅動標的1, qty=1 * 可買, side=OrderSide.BUY)

    # ---------- 出場：按持倉模式用唔同規則 ----------

    def 檢查出場(self):
        if self.持倉模式 == 'BO':
            觸發 = self.突破出場訊號()
        else:
            觸發 = self.撈底出場訊號()

        if 觸發 and self.有貨可賣():
            self.市價全部賣出()
            self.持倉模式 = ''

    def 突破出場訊號(self):
        # 價格跌穿20日新低（對上20根完成K線嘅最低）
        現價 = current_price(symbol=self.驅動標的1, price_type=THType.RTH)
        前低 = bar_custom(symbol=self.驅動標的1, data_type=BarDataType.LOW,
                          custom_num=self.出場日數, custom_type=CustomType.K_DAY,
                          select=2, session_type=THType.RTH)
        return 現價 < 前低

    def 撈底出場訊號(self):
        # RSI(2) 反彈到超買區就走
        rsi值 = rsi(symbol=self.驅動標的1, period=self.RSI日數,
                    bar_type=BarType.K_DAY, select=1, session_type=THType.RTH)
        return rsi值 > self.RSI賣出線

    def 有貨可賣(self):
        可賣 = max_qty_to_sell(symbol=self.驅動標的1)
        一手 = lot_size(symbol=self.驅動標的1)
        return 可賣 >= 一手

    def 市價全部賣出(self):
        可賣 = max_qty_to_sell(symbol=self.驅動標的1)
        place_market(symbol=self.驅動標的1, qty=1 * 可賣, side=OrderSide.SELL)
