# Vol-Target（QQQ / SPY / GOOG）富途牛牛量化策略
#
# 回測設定：驅動標的請選「日 K 收市」觸發。
#
# 規則：
#   1. 收集 41 個完成日線收市價，計出 40 個日回報。
#   2. 實現波動 = 40 日日回報的母體標準差 * sqrt(252)。
#   3. 目標槓桿 = clamp(40% / 實現波動, 0x, 2x)。
#   4. 每日按目標槓桿加倉或減倉，從不因技術指標清倉。
#
# 注意：
# - 富途回測的融資利息、佣金、滑點必須在回測設定另行填寫。
# - 此策略使用 max_qty_to_buy_on_margin 的剩餘 buying power 推算 2x 滿倉；
#   請把回測帳戶的最大槓桿同 self.最大槓桿設定為一致。
# - 策略重啟會重新累積 41 日資料；回測起始日請預留至少 41 個交易日 warm-up。

class Strategy(StrategyBase):

    def initialize(self):
        declare_strategy_type(AlgoStrategyType.SECURITY)
        self.trigger_symbols()
        self.custom_indicator()
        self.global_variables()

    def trigger_symbols(self):
        self.驅動標的 = declare_trig_symbol()

    def global_variables(self):
        self.目標年化波動 = 0.40
        self.波動窗口 = 40
        self.最大槓桿 = 2.0
        self.最小槓桿 = 0.0
        self.收市價 = []

    def custom_indicator(self):
        pass

    def handle_data(self):
        # 請在富途把觸發頻率設為「日 K 收市」；否則 tick 更新會重複加入同一日價格。
        收市價 = current_price(symbol=self.驅動標的, price_type=THType.RTH)
        if 收市價 <= 0:
            return

        self.收市價.append(收市價)
        if len(self.收市價) > self.波動窗口 + 1:
            self.收市價.pop(0)

        if len(self.收市價) < self.波動窗口 + 1:
            return

        日回報 = []
        for i in range(1, len(self.收市價)):
            前收市價 = self.收市價[i - 1]
            今收市價 = self.收市價[i]
            if 前收市價 > 0:
                日回報.append(今收市價 / 前收市價 - 1.0)

        if len(日回報) < self.波動窗口:
            return

        平均日回報 = sum(日回報) / len(日回報)
        方差 = sum((回報 - 平均日回報) ** 2 for 回報 in 日回報) / len(日回報)
        實現波動 = (方差 ** 0.5) * (252 ** 0.5)
        if 實現波動 <= 0:
            目標槓桿 = 1.0
        else:
            原始槓桿 = self.目標年化波動 / 實現波動
            目標槓桿 = max(self.最小槓桿, min(self.最大槓桿, 原始槓桿))

        現有股數 = position_holding_qty(symbol=self.驅動標的)
        可買股數 = max_qty_to_buy_on_margin(
            symbol=self.驅動標的,
            order_type=OrdType.MKT,
            price=收市價,
            order_trade_session_type=TSType.RTH,
        )

        # 現有倉位 + 尚可買股數 = 帳戶在現價下可達的最大倉位。
        # 將它按目標槓桿比例縮放，令 2x 對應滿 margin 倉位、1x 約對應一半。
        最大可達股數 = 現有股數 + 可買股數
        一手 = lot_size(symbol=self.驅動標的)
        if 一手 <= 0:
            return
        目標股數 = int((最大可達股數 * 目標槓桿 / self.最大槓桿) // 一手) * 一手

        if 目標股數 > 現有股數:
            買入股數 = min(目標股數 - 現有股數, 可買股數)
            買入股數 = int(買入股數 // 一手) * 一手
            if 買入股數 > 0:
                place_market(symbol=self.驅動標的, qty=買入股數, side=OrderSide.BUY)
        elif 目標股數 < 現有股數:
            可賣股數 = max_qty_to_sell(symbol=self.驅動標的)
            賣出股數 = min(現有股數 - 目標股數, 可賣股數)
            賣出股數 = int(賣出股數 // 一手) * 一手
            if 賣出股數 > 0:
                place_market(symbol=self.驅動標的, qty=賣出股數, side=OrderSide.SELL)
