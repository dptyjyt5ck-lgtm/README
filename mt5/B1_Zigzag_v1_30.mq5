//+------------------------------------------------------------------+
//|  B1_Zigzag.mq5 v1.30 (демо) — система B1, стратегия «Зигзаг»      |
//|  v1.30 (14.10.2026), от v1.29 — версия для наблюдения на демо:    |
//|   • вход настоящими лимитными ордерами BuyLimit/SellLimit со      |
//|     общим стопом (тейка нет, выходом управляет советник);         |
//|     лимитки стоят только у ОДНОЙ фигуры: новая фигура заменяет    |
//|     старую неисполненную, фигуру с открытой позицией не трогаем;  |
//|     исполнение считается по реальному объёму из истории ордеров;  |
//|   • новости: за NewsWindowMin до новости лимитки снимаются, после |
//|     окна — выставляются снова; нет файла новостей — фильтр        |
//|     выключается с предупреждением, советник работает дальше;      |
//|   • риск по умолчанию 3 %, потолок MaxRiskPercent 5 %;          |
//|     если с минимальным лотом на уровнях риск выше потолка —       |
//|     снимаем уровни, начиная с самого дальнего                     |
//|     от стопа (0,618); даже 0,01 лота выше потолка — пропуск;       |
//|   • объёмы округляются по шагу лота, цены — по размеру тика;      |
//|     счётчик ошибок — свой у каждого уровня;                       |
//|   • отчёт: CSV в Common\Files (строка на каждую закрытую фигуру), |
//|     итог месяца в журнале и на графике;                           |
//|   • реальный счёт: советник не запускается без AllowRealAccount.  |
//|  v1.29: каждый уровень получает не меньше минимального лота       |
//|  (0,01): на маленьком депозите риск на фигуру выше RiskPercent,   |
//|  фактический риск пишется в журнал при каждой фигуре.             |
//|  v1.28: окно экстремума точки A — 72 часа (было 96).              |
//|  v1.27: поздняя фигура (цена уже прошла 0,618, пока ZigZag        |
//|  подтверждал B) не выбрасывается: пройденные уровни пропускаем,   |
//|  их объём переносим на первый ещё не пройденный уровень.          |
//|  v1.26: вход засчитывается только по реально исполненному объёму; |
//|  мелкая позиция закрывается частями хотя бы по минимальному лоту. |
//|  v1.25: за B закрыть 25 % начального объёма, стоп в безубыток;    |
//|  на 1,618 закрыть ещё 30 %, трейлинг 3 ATR на остаток; застой.    |
//|  v1.23: точка A — настоящий разворот после тренда.                |
//|  v1.22: частичное закрытие на неттинге — встречной сделкой.       |
//|                                                                  |
//|  Обозначения как на рисунке пользователя (продажа):              |
//|    A — начало импульса, B — конец импульса, BC — коррекция.      |
//|    Сетка: 0 на A, 1 на B. Лимитки 0,618 / 0,5 / 0,382 / 0,236 /  |
//|    0,14; стоп общий −0,14 за точкой A.                           |
//|  Только для ТЕСТЕРА и ДЕМО-счёта. Реальный счёт не подключать.     |
//+------------------------------------------------------------------+
#property copyright "AI Trading Desk / Claude, 14.10.2026"
#property version   "1.30"

#include <Trade\Trade.mqh>

//--- входные параметры
input bool   UseZone           = false;  // требовать, чтобы A стояла в зоне крупного разворота 24/24 (старое правило B1)
input int    ExtremeHours      = 72;     // A — самая крайняя цена за столько часов до неё
input double TrendMinATR       = 8.0;    // тренд пришёл в A: от противоположного края этого окна до A ≥ N·ATR (0 = выкл.)
input double ImpulseMinATR     = 2.0;    // импульс AB ≥ N·ATR, мелкие волны не торгуем (0 = выкл.)
input int    TrendBars         = 48;     // фильтр «не пила»: сколько часовых свечей перед A смотреть
input double TrendEff          = 0.30;   // ход к A / весь пройденный путь за TrendBars свечей ≥ этого (0 = выкл.)
input double RiskPercent       = 3.0;    // риск на фигуру, % баланса (если исполнятся все 5 лимиток)
input double MaxRiskPercent    = 5.0;    // потолок риска на фигуру, % баланса (из-за мин. лота риск бывает выше RiskPercent)
input double StopK             = 0.14;   // стоп: −0,14 сетки за точкой A
input double Weight618         = 60.0;   // доля объёма на 0,618, %; остаток поровну на 0,5/0,382/0,236/0,14 (по 10 %)
input double TargetK           = 1.618;  // цель: уровень сетки (1.618 по правилу; 1.0 = точка B)
input double TrailATRMult      = 3.0;    // трейлинг остатка: N × ATR14(H1)
input int    MaxHoldDays       = 28;     // выход по времени
input int    SetupMaxBars      = 0;      // 0 = лимитки живут, пока цена не ушла за B; >0 = снять через N часовых свечей
input bool   DropReplacedZones = true;   // не брать зону 24/24, если её вершину потом переписала более крайняя (до точки A)
input bool   UseNewsFilter     = true;   // снимать лимитки на ±NewsWindowMin от важных новостей
input string NewsFile          = "b1_news_utc.csv"; // файл в папке Common\Files терминала
input int    NewsWindowMin     = 15;
input int    ServerTimeMode    = 0;      // 0 = время сервера NY+7 (UTC+2 зимой / UTC+3 летом), 1 = фиксированный сдвиг
input int    ServerGMTOffset   = 2;      // для режима 1: часы сервера минус UTC
input int    HistoryBars       = 4000;   // сколько часовых свечей истории взять для разметки уровней
input bool   DrawObjects       = true;   // рисовать фигуры с входом
input bool   BreakevenAtB      = true;   // цена ушла за B после входа — стоп в безубыток с учётом спреда
input double PartialAtB        = 25.0;   // за B закрыть столько % НАЧАЛЬНОГО объёма (0 = не закрывать)
input double TargetPart        = 30.0;   // на цели закрыть ещё столько % НАЧАЛЬНОГО объёма; остаток — на трейлинг
input int    BEExtraPoints     = 0;      // безубыток: к спреду добавить столько пунктов (комиссия, проскальзывание)
input int    StagBars          = 12;     // выход из застоя: столько закрытых H1-свечей без нового экстремума (0 = выкл.)
input double StagMinR          = 0.7;    // ...если прибыль уже доходила до +N R
input double StagGiveBack      = 40.0;   // ...и отдано не меньше N % от максимальной прибыли
input double StagMinCurR       = 0.2;    // ...а текущая прибыль ещё не меньше +N R
#define DrawRejected false               // подписи отклонённых фигур выключены насовсем; причины — в таблице журнала
#define RejectMinATR 1.0
input long   Magic             = 260113;
input bool   AllowRealAccount  = false;  // false = на РЕАЛЬНОМ счёте советник не запустится (только тестер и демо)

//--- причины и счётчики (статистика печатается в журнал в конце работы)
#define R_LEGS      0
#define R_SAMEBAR   1
#define R_NOTEXT    2
#define R_NOZONE    3
#define R_SETUP     4
#define R_GONE      5
#define R_STOPFIRST 6
#define R_EXPIRED   7
#define R_BUSY      8
#define R_NEWS      9
#define R_VOL       10
#define R_TRADES    11
#define R_FILLS     12
#define R_LATE      13
#define R_BE        14
#define R_NOTREND   15
#define R_SMALL     16
#define R_CHOP      17
#define R_STAG      18
#define R_LATEMOVE  19
#define R_REPLACED  20
#define R_RISKCAP   21
#define R_CAPDROP   22
#define R_MISSED    23
#define R_SKIPSTOP  24
#define R_ORDFAIL   25
#define R_ACTIVE    26
#define R_N         27
int    stat[R_N];
string statName[R_N] = {"новых ног ZigZag(3,1)", "A и B на одной свече", "A не самый крайний за ExtremeHours",
                        "A не в зоне разворота 24/24", "новых фигур (прошли фильтры)",
                        "цена ушла за B, лимитки не исполнились", "стоп задет до входа", "истёк срок лимиток",
                        "пропуск: уже есть позиция", "лимитка пропущена: новости", "пропуск: не удалось рассчитать объём",
                        "фигур с входом (сделок)", "исполнено лимиток (уровней)",
                        "пропуск: фигура подтвердилась, когда цена прошла все уровни", "сделок, где стоп ушёл в безубыток за B",
                        "A без тренда перед ней (боковик)", "импульс AB слишком мелкий",
                        "движение к A не направленное (пила)", "закрыто из-за застоя после прибыли",
                        "поздняя фигура: пройденные уровни пропущены, объём перенесён",
                        "лимитки сняты: появилась более новая фигура", "пропуск: даже 0,01 лота — риск выше MaxRiskPercent",
                        "уровней снято из-за потолка MaxRiskPercent", "уровень пройден, когда ордера не было",
                        "уровень пропущен: стоп ближе, чем разрешает брокер", "уровень пропущен: ордер не выставился 5 раз",
                        "фигур, по которым выставлены лимитки"};
string statShort[R_N] = {"", "A=B свеча", "не экстр.", "нет зоны 24/24", "", "ушла за B", "стоп до входа",
                         "срок", "занято", "новости", "объём", "", "", "поздно", "", "боковик", "мелко", "пила", "", "",
                         "заменена", "риск", "", "", "", "", ""};

//--- уровни сетки (0 на A, 1 на B): первым исполняется 0,618
const double LR[5] = {0.618, 0.5, 0.382, 0.236, 0.14};
string       LN[5] = {"0,618", "0,5", "0,382", "0,236", "0,14"};
double       W[5];

//--- структуры
struct Pivot { int kind; int index; double price; };              // kind: 1 = High, -1 = Low
struct CtxEv { int known; int dead; int kind; int pidx; double zlo; double zhi; };
// фигура; по каждому уровню k: lots — план, got — исполнено, tk — тикет текущей лимитки (0 = ордера нет)
struct Setup { int id; int aIdx; int bIdx; double A; double B; bool buy; double lv[5]; double lots[5]; bool done[5];
               double stop; double target1; int j0; bool alive; bool any; double w[5];
               ulong tk[5]; double px[5]; double sent[5]; double gotOrd[5]; double got[5]; int fails[5]; int miss[5];
               bool newsOff[5]; bool delByUs[5]; datetime lastTry[5]; bool hasOrd; bool sized; double planRisk; };
struct Group { bool on; int sid; bool buy; double B; double target1; double stop0; double initVol; bool beDone; bool partDone; bool tpDone;
               datetime opened; double ext; int lastExtH1; double planRisk; double slWant; datetime lastFill; bool seenPos; };

//--- данные H1 (по возрастанию времени)
MqlRates H[];
double   ATR[];
int      NH = 0;

Pivot    zz[];        int nzz = 0;          // ZigZag(3,1) — структура A→B
Pivot    mz[];        int nmz = 0;          // ZigZag(24,24) — крупные развороты для зон
CtxEv    ev[];        int nev = 0;
Setup    st[];        int nst = 0;          int nextId = 1;
Group    grp;
string   grpLevels  = "";                    // какие уровни исполнились (для отчёта)
string   grpExitWhy = "";                    // причина выхода, если закрывал советник
ulong    grpPos[];                           // идентификаторы позиций фигуры (для подсчёта прибыли)
string   seenKeys[];  int nseen = 0;
int      actSid = -1;                        // фигура, у которой сейчас стоят лимитки (если позиции нет)

datetime newsT[];     string newsC[];  int nnews = 0;  int newsPtr = 0;
bool     newsOK = false, newsNow = false;
long     newsMinute = -1;
string   newsWarn = "";
datetime lastM15 = 0, lastNoTradeLog = 0;
bool     ready = false;
CTrade   trade;
int      objN = 0;
string   banner = "", curMonthLine = "", prevMonthLine = "";
int      curYM = 0;

//+------------------------------------------------------------------+
int OnInit()
  {
   //--- сброс состояния: при смене таймфрейма/параметров советник не выгружается
   NH = 0; nzz = 0; nmz = 0; nev = 0; nst = 0; nextId = 1; nseen = 0; nnews = 0; newsPtr = 0;
   ArrayResize(H, 0); ArrayResize(ATR, 0); ArrayResize(zz, 0); ArrayResize(mz, 0); ArrayResize(ev, 0);
   ArrayResize(st, 0); ArrayResize(seenKeys, 0); ArrayResize(newsT, 0); ArrayResize(newsC, 0);
   ready = false; lastM15 = 0; actSid = -1; newsOK = false; newsNow = false; newsMinute = -1; newsWarn = ""; curYM = 0;
   ResetGrp();

   trade.SetExpertMagicNumber(Magic);
   trade.SetDeviationInPoints(30);
   trade.SetTypeFillingBySymbol(_Symbol);

   bool tester = (MQLInfoInteger(MQL_TESTER) != 0);
   //--- реальный счёт — только по явному разрешению
   if(!tester && AccountInfoInteger(ACCOUNT_TRADE_MODE) == ACCOUNT_TRADE_MODE_REAL && !AllowRealAccount)
     {
      string m = "B1 Зигзаг v1.30: это РЕАЛЬНЫЙ счёт. Советник только для тестера и демо-счёта — работа остановлена. "
                 "(Если очень нужно — параметр AllowRealAccount = true, но стратегия не доказала прибыльность.)";
      Print(m); Alert(m); Comment(m);
      return(INIT_FAILED);
     }
   if(Weight618 <= 0 || Weight618 > 100) { Print("Weight618 должен быть в пределах 1…100"); return(INIT_PARAMETERS_INCORRECT); }
   if(RiskPercent <= 0 || MaxRiskPercent <= 0) { Print("RiskPercent и MaxRiskPercent должны быть больше 0"); return(INIT_PARAMETERS_INCORRECT); }
   if(MaxRiskPercent < RiskPercent)
      PrintFormat("Внимание: MaxRiskPercent (%.1f%%) меньше RiskPercent (%.1f%%) — объём будет урезаться почти всегда", MaxRiskPercent, RiskPercent);
   W[0] = Weight618 / 100.0;
   for(int k = 1; k < 5; k++) W[k] = (1.0 - W[0]) / 4.0;
   //--- новости: нет файла — не останавливаемся, а выключаем фильтр и предупреждаем
   if(UseNewsFilter)
     {
      if(LoadNews()) newsOK = true;
      else
        {
         newsWarn = "ВНИМАНИЕ: файл новостей " + NewsFile + " (папка Common\\Files) не найден или пуст — фильтр новостей ВЫКЛЮЧЕН";
         Print(newsWarn);
        }
     }
   ArrayInitialize(stat, 0);
   if(tester) FileDelete(CsvName(), FILE_COMMON);                    // в тестере каждый прогон — свой отчёт
   string acc = IsHedge() ? "хеджинг" : "неттинг";
   banner = StringFormat("B1 Зигзаг v1.30 (демо) | %s | %s | риск %.1f%% (потолок %.1f%%) | экстр. %d ч | тренд ≥ %.1f ATR, ход ≥ %.2f | импульс ≥ %.1f ATR | за B: %.0f%% + БУ | цель %.3f: %.0f%% + трейл %.1f ATR | застой %d св.",
                         _Symbol, acc, RiskPercent, MaxRiskPercent, ExtremeHours, TrendMinATR, TrendEff, ImpulseMinATR,
                         PartialAtB, TargetK, TargetPart, TrailATRMult, StagBars);
   Print(banner);
   Print("Только для ТЕСТЕРА и ДЕМО-счёта. Отчёт по сделкам: Common\\Files\\", CsvName());
   if(!IsHedge()) Print("Неттинговый счёт: не торгуйте вручную этим же инструментом — позиция у бота и у вас будет общей.");
   //--- лимитки, оставшиеся от прошлого запуска, снимаем: советник выставит их заново по своей разметке
   DeleteAllOurOrders("перезапуск советника: старая лимитка снята, будет выставлена заново");
   UpdateComment();
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   //--- без советника лимитки никто не сопровождает — снимаем (при следующем запуске выставятся снова)
   DeleteAllOurOrders("советник остановлен: лимитка снята");
   if(grp.on) SaveState();
   Print("===== B1 Зигзаг v1.30: статистика за период работы =====");
   for(int k = 0; k < R_N; k++) PrintFormat("%-60s %6d", statName[k], stat[k]);
   if(curMonthLine != "") Print(curMonthLine);
   if(reason == REASON_REMOVE) Comment("");
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   if(!ready)
     {
      if(!InitHistory()) return;
      ready = true;
      RestoreGroup();                                                  // позиция осталась от прошлого запуска?
      InitMonth();
      UpdateComment();
     }
   //--- новые закрытые часовые свечи
   MqlRates tmp[];
   int n = CopyRates(_Symbol, PERIOD_H1, 1, 30, tmp);
   if(n > 0)
      for(int k = 0; k < n; k++)
         if(NH == 0 || tmp[k].time > H[NH - 1].time) { AppendH1(tmp[k]); ProcessH1(NH - 1, true); }
   SyncAll();                                                          // исполнения лимиток
   CheckGroup();                                                       // позиция закрылась?
   UpdateNews();
   ManageSetups();                                                     // снять / заменить / выставить лимитки
   CheckBreakeven();
   CheckTargets();
   //--- сопровождение позиций на закрытии 15-минуток
   datetime m15 = iTime(_Symbol, PERIOD_M15, 0);
   if(m15 != lastM15)
     {
      lastM15 = m15;
      ManageTrades();
      FixSL(true);
      CleanOrphans();
      CheckMonth();
      if(grp.on) SaveState();
      UpdateComment();
     }
  }

// исполнение сделки — сразу сверяем лимитки (не дожидаясь следующего тика)
void OnTradeTransaction(const MqlTradeTransaction &trans, const MqlTradeRequest &request, const MqlTradeResult &result)
  {
   if(!ready) return;
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
   if(trans.symbol != _Symbol) return;
   SyncAll();
  }

//+------------------------------------------------------------------+
bool InitHistory()
  {
   MqlRates r[];
   int n = CopyRates(_Symbol, PERIOD_H1, 1, HistoryBars, r);
   if(n < 300) { Print("Мало истории H1: ", n); return(false); }
   for(int k = 0; k < n; k++) { AppendH1(r[k]); ProcessH1(NH - 1, false); }
   Print("История H1 загружена: ", NH, " свечей, крупных разворотов: ", nev);
   return(true);
  }

void AppendH1(const MqlRates &r)
  {
   ArrayResize(H, NH + 1, 10000);
   ArrayResize(ATR, NH + 1, 10000);
   H[NH] = r;
   double s = 0; int cnt = 0;
   for(int q = NH; q >= 0 && cnt < 14; q--, cnt++)
     {
      double tr_ = (q == 0) ? H[q].high - H[q].low
                   : MathMax(H[q].high, H[q - 1].close) - MathMin(H[q].low, H[q - 1].close);
      s += tr_;
     }
   ATR[NH] = s / cnt;
   NH++;
  }

//+------------------------------------------------------------------+
//| Пивоты, известные на закрытии свечи i (кандидат j = i - right)    |
//+------------------------------------------------------------------+
int PivotsAt(int i, int left, int right, Pivot &out[])
  {
   ArrayResize(out, 0);
   int j = i - right;
   if(j - left < 0) return(0);
   double lh = -DBL_MAX, ll = DBL_MAX, rh = -DBL_MAX, rl = DBL_MAX;
   for(int q = j - left; q < j; q++) { lh = MathMax(lh, H[q].high); ll = MathMin(ll, H[q].low); }
   for(int q = j + 1; q <= i; q++)    { rh = MathMax(rh, H[q].high); rl = MathMin(rl, H[q].low); }
   int c = 0;
   if(H[j].high > lh && H[j].high >= rh) { ArrayResize(out, c + 1); out[c].kind = 1;  out[c].index = j; out[c].price = H[j].high; c++; }
   if(H[j].low  < ll && H[j].low  <= rl) { ArrayResize(out, c + 1); out[c].kind = -1; out[c].index = j; out[c].price = H[j].low;  c++; }
   return(c);
  }

// обновить зигзаг; вернуть число событий. repl[k] = индекс прежней вершины, если событие — продление, иначе -1
int ZZUpdate(Pivot &p[], int &np, int i, int left, int right, Pivot &events[], int &repl[])
  {
   ArrayResize(events, 0); ArrayResize(repl, 0);
   Pivot c[];
   int nc = PivotsAt(i, left, right, c);
   if(nc == 2 && np > 0 && c[0].kind == p[np - 1].kind) { Pivot t = c[0]; c[0] = c[1]; c[1] = t; }
   int ne = 0;
   for(int k = 0; k < nc; k++)
     {
      if(np > 0 && p[np - 1].kind == c[k].kind)
        {
         bool more = (c[k].kind == 1) ? c[k].price > p[np - 1].price : c[k].price < p[np - 1].price;
         if(more)
           {
            int old = p[np - 1].index;
            p[np - 1] = c[k];
            ArrayResize(events, ne + 1); ArrayResize(repl, ne + 1); events[ne] = c[k]; repl[ne] = old; ne++;
           }
        }
      else
        {
         ArrayResize(p, np + 1, 1000); p[np++] = c[k];
         ArrayResize(events, ne + 1); ArrayResize(repl, ne + 1); events[ne] = c[k]; repl[ne] = -1; ne++;
        }
     }
   return(ne);
  }

//+------------------------------------------------------------------+
//| Контекст точки A. Возвращает 0, если всё в порядке, иначе код     |
//| причины.                                                         |
//+------------------------------------------------------------------+
int CtxOk(int idx, int kind, double price, int now)
  {
   //--- A — самая крайняя цена за ExtremeHours часов
   int lo = MathMax(0, idx - ExtremeHours);
   double opp = (kind == 1) ? DBL_MAX : -DBL_MAX;                     // противоположный край окна
   for(int q = lo; q <= idx; q++)
     {
      if(kind == 1  && price < H[q].high - 1e-12) return(R_NOTEXT);
      if(kind == -1 && price > H[q].low  + 1e-12) return(R_NOTEXT);
      opp = (kind == 1) ? MathMin(opp, H[q].low) : MathMax(opp, H[q].high);
     }
   //--- тренд пришёл в A: цена прошла к A не меньше TrendMinATR·ATR (в боковике — нет)
   if(TrendMinATR > 0 && MathAbs(price - opp) < TrendMinATR * ATR[idx]) return(R_NOTREND);
   //--- движение к A направленное, а не пила: чистый ход / весь путь цены за TrendBars свечей
   if(TrendEff > 0 && TrendBars > 0)
     {
      int s0 = idx - TrendBars;
      if(s0 < 1) return(R_CHOP);
      double path = MathAbs(price - H[idx].close);
      for(int q = s0 + 1; q <= idx; q++) path += MathAbs(H[q].close - H[q - 1].close);
      double net = (kind == 1) ? price - H[s0].close : H[s0].close - price;
      if(path <= 0 || net / path < TrendEff) return(R_CHOP);
     }
   if(!UseZone) return(0);
   //--- старое правило B1: A в зоне крупного разворота 24/24, известного до A
   double tol = 0.25 * ATR[idx];
   int lim = MathMin(now, idx);
   for(int q = nev - 1; q >= 0; q--)
     {
      if(ev[q].known >= lim) continue;
      if(DropReplacedZones && ev[q].dead < lim) continue;
      if(ev[q].pidx < idx - 2160) break;
      if(ev[q].kind == kind && ev[q].pidx < idx && ev[q].zlo - tol <= price && price <= ev[q].zhi + tol) return(0);
     }
   return(R_NOZONE);
  }

bool Seen(string key)
  {
   for(int k = nseen - 1; k >= 0 && k >= nseen - 50; k--) if(seenKeys[k] == key) return(true);
   ArrayResize(seenKeys, nseen + 1, 1000); seenKeys[nseen++] = key;
   return(false);
  }

int FindSetup(int id)
  {
   if(id < 0) return(-1);
   for(int s = nst - 1; s >= 0; s--) if(st[s].id == id) return(s);
   return(-1);
  }

// снять фигуру и её лимитки; why < 0 — без учёта в статистике
void Kill(int s, int why)
  {
   st[s].alive = false;
   DeleteSetupOrders(s);                         // не снялись сейчас — повтор в ManageSetups на следующих тиках
   if(why < 0) return;
   stat[why]++;
   if(DrawObjects && DrawRejected && MathAbs(st[s].B - st[s].A) >= RejectMinATR * ATR[st[s].bIdx])
      DrawReject(st[s].aIdx, st[s].A, st[s].bIdx, st[s].B, why);
  }

//+------------------------------------------------------------------+
//| Обработка закрытой часовой свечи i                                |
//+------------------------------------------------------------------+
void ProcessH1(int i, bool live)
  {
   //--- 1) фигуры по закрытой свече
   for(int s = 0; s < nst; s++)
     {
      if(!st[s].alive || i < st[s].j0) continue;
      if(!live)
        {
         // в истории до начала работы не торгуем: фигура, которую цена уже отработала, снимается
         bool buy = st[s].buy;
         bool beyondB = buy ? H[i].high >= st[s].B : H[i].low <= st[s].B;
         bool touch   = buy ? H[i].low <= st[s].lv[0] : H[i].high >= st[s].lv[0];
         if(beyondB || touch) st[s].alive = false;
         continue;
        }
      if(SetupMaxBars > 0 && !st[s].any && i - st[s].j0 + 1 >= SetupMaxBars) Kill(s, R_EXPIRED);
     }
   //--- 2) крупные развороты для зон уровня
   Pivot e[]; int rp[];
   int ne = ZZUpdate(mz, nmz, i, 24, 24, e, rp);
   for(int k = 0; k < ne; k++)
     {
      if(rp[k] >= 0)       // вершину переписала более крайняя: старая зона перестаёт действовать с этой свечи
         for(int q = nev - 1; q >= 0; q--)
            if(ev[q].pidx == rp[k] && ev[q].kind == e[k].kind && ev[q].dead == INT_MAX) { ev[q].dead = i; break; }
      int j = e[k].index;
      ArrayResize(ev, nev + 1, 1000);
      ev[nev].known = i; ev[nev].dead = INT_MAX; ev[nev].kind = e[k].kind; ev[nev].pidx = j;
      if(e[k].kind == 1) { ev[nev].zlo = (j > 0) ? MathMax(H[j].close, H[j - 1].close) : H[j].close; ev[nev].zhi = e[k].price; }
      else               { ev[nev].zlo = e[k].price; ev[nev].zhi = (j > 0) ? MathMin(H[j].close, H[j - 1].close) : H[j].close; }
      nev++;
     }
   //--- 3) структура ZigZag(3,1): новая фигура A→B
   Pivot e2[]; int rp2[];
   if(ZZUpdate(zz, nzz, i, 3, 1, e2, rp2) == 0 || nzz < 2) return;
   Pivot pa = zz[nzz - 2], pb = zz[nzz - 1];
   double imp = pb.price - pa.price;
   if(imp == 0) return;
   if(Seen(IntegerToString(pa.index) + ":" + IntegerToString(pb.index))) return;
   if(live) stat[R_LEGS]++;
   if(pa.index == pb.index) { if(live) stat[R_SAMEBAR]++; return; }
   if(ImpulseMinATR > 0 && MathAbs(imp) < ImpulseMinATR * ATR[i]) { if(live) stat[R_SMALL]++; return; }
   int why = CtxOk(pa.index, pa.kind, pa.price, i);
   if(why != 0)
     {
      if(live)
        {
         stat[why]++;
         if(DrawObjects && DrawRejected && MathAbs(imp) >= RejectMinATR * ATR[i]) DrawReject(pa.index, pa.price, pb.index, pb.price, why);
        }
      return;
     }
   Setup x;
   x.id = nextId++;
   x.aIdx = pa.index; x.bIdx = pb.index; x.A = pa.price; x.B = pb.price; x.buy = imp > 0;
   for(int q = 0; q < 5; q++)
     {
      x.lv[q] = pa.price + LR[q] * imp; x.lots[q] = 0; x.done[q] = false; x.w[q] = W[q];
      x.tk[q] = 0; x.px[q] = 0; x.sent[q] = 0; x.gotOrd[q] = 0; x.got[q] = 0; x.fails[q] = 0; x.miss[q] = 0;
      x.newsOff[q] = false; x.delByUs[q] = false; x.lastTry[q] = 0;
     }
   x.stop = pa.price - StopK * imp;
   x.target1 = pa.price + TargetK * imp;
   x.j0 = i + 1; x.alive = true; x.any = false; x.hasOrd = false; x.sized = false; x.planRisk = 0;
   ArrayResize(st, nst + 1, 1000);
   st[nst++] = x;
   if(live)
     {
      //--- фигура подтвердилась поздно: пройденные уровни пропускаем, их объём — на первый не пройденный;
      //    прошла все — фигуры нет
      if(!LateShift(nst - 1))
        {
         st[nst - 1].alive = false;
         stat[R_LATE]++;
         if(DrawObjects && DrawRejected && MathAbs(imp) >= RejectMinATR * ATR[i]) DrawReject(pa.index, pa.price, pb.index, pb.price, R_LATE);
         return;
        }
      stat[R_SETUP]++;
      PrintFormat("Новая фигура #%d: %s, A=%s B=%s, стоп %s, цель %s", x.id, x.buy ? "покупка" : "продажа",
                  DoubleToString(x.A, _Digits), DoubleToString(x.B, _Digits), DoubleToString(x.stop, _Digits), DoubleToString(x.target1, _Digits));
     }
   if(nst > 2000) Compact();
  }

void Compact()
  {
   int w = 0;
   for(int s = 0; s < nst; s++) if(st[s].alive || st[s].hasOrd) st[w++] = st[s];
   nst = w; ArrayResize(st, nst, 1000);
  }

// уровни, которые цена уже прошла (лимитку не поставить), пропускаем; их объём — на первый не пройденный.
// false — цена прошла все уровни
bool LateShift(int s)
  {
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID), ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double moved = 0; int k0 = -1, last = -1;
   for(int k = 0; k < 5; k++)
     {
      if(st[s].done[k] || st[s].w[k] <= 0) continue;
      bool passed = st[s].buy ? ask <= st[s].lv[k] : bid >= st[s].lv[k];
      if(passed) { moved += st[s].w[k]; st[s].w[k] = 0; st[s].done[k] = true; last = k; }
      else { k0 = k; break; }
     }
   if(k0 < 0) return(false);
   if(moved > 0)
     {
      st[s].w[k0] += moved;
      stat[R_LATEMOVE]++;
      PrintFormat("Фигура #%d: уровни до %s уже пройдены, их объём (%.0f%%) перенесён на %s", st[s].id, LN[last], moved * 100, LN[k0]);
     }
   return(true);
  }

//+------------------------------------------------------------------+
//| Вспомогательные: цены, объёмы, торговля разрешена                 |
//+------------------------------------------------------------------+
bool IsHedge() { return(AccountInfoInteger(ACCOUNT_MARGIN_MODE) == ACCOUNT_MARGIN_MODE_RETAIL_HEDGING); }

double TickSz() { double t = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE); return(t > 0 ? t : _Point); }
double NormPrice(double p) { double t = TickSz(); return(NormalizeDouble(MathRound(p / t) * t, _Digits)); }
double PriceDown(double p) { double t = TickSz(); return(NormalizeDouble(MathFloor(p / t + 1e-8) * t, _Digits)); }
double PriceUp(double p)   { double t = TickSz(); return(NormalizeDouble(MathCeil(p / t - 1e-8) * t, _Digits)); }

int VolDigits()
  {
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   int d = 0;
   while(d < 8 && MathAbs(step * MathPow(10, d) - MathRound(step * MathPow(10, d))) > 1e-6) d++;
   return(d);
  }

// объём вниз по шагу лота (а не до 2 знаков)
double NormVol(double v)
  {
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(step <= 0) return(NormalizeDouble(v, 2));
   return(NormalizeDouble(MathFloor(v / step + 1e-7) * step, VolDigits()));
  }

// минимальная дистанция от цены для ордеров и стопов: уровень стопов и уровень заморозки брокера
double MinDist()
  {
   long sl = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   long fl = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_FREEZE_LEVEL);
   long mx = (sl > fl) ? sl : fl;
   return((double)mx * _Point);
  }

bool CanTrade()
  {
   if(MQLInfoInteger(MQL_TESTER) != 0) return(true);
   if(TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) == 0 || MQLInfoInteger(MQL_TRADE_ALLOWED) == 0)
     {
      if(TimeCurrent() - lastNoTradeLog > 3600)
        {
         lastNoTradeLog = TimeCurrent();
         Print("Автоторговля выключена: нажмите кнопку «Алго-трейдинг» и разрешите торговлю в свойствах советника");
        }
      return(false);
     }
   return(true);
  }

ENUM_ORDER_TYPE_TIME TimeMode()
  {
   int em = (int)SymbolInfoInteger(_Symbol, SYMBOL_EXPIRATION_MODE);
   if(em == 0 || (em & SYMBOL_EXPIRATION_GTC) != 0) return(ORDER_TIME_GTC);
   if((em & SYMBOL_EXPIRATION_DAY) != 0) return(ORDER_TIME_DAY);          // брокер снимет вечером — советник выставит снова
   return(ORDER_TIME_GTC);
  }

bool RcOk()
  {
   uint rc = trade.ResultRetcode();
   return(rc == TRADE_RETCODE_DONE || rc == TRADE_RETCODE_DONE_PARTIAL);
  }

//+------------------------------------------------------------------+
//| Позиции бота по символу                                          |
//+------------------------------------------------------------------+
int OurPositions(ulong &tk[])
  {
   ArrayResize(tk, 0); int n = 0;
   for(int p = PositionsTotal() - 1; p >= 0; p--)
     {
      ulong t = PositionGetTicket(p);
      if(t == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol || PositionGetInteger(POSITION_MAGIC) != Magic) continue;
      ArrayResize(tk, n + 1); tk[n++] = t;
     }
   return(n);
  }

void ResetGrp()
  {
   grp.on = false; grp.sid = -1; grp.buy = false; grp.B = 0; grp.target1 = 0; grp.stop0 = 0; grp.initVol = 0;
   grp.beDone = false; grp.partDone = false; grp.tpDone = false; grp.opened = 0; grp.ext = 0; grp.lastExtH1 = 0;
   grp.planRisk = 0; grp.slWant = 0; grp.lastFill = 0; grp.seenPos = false;
   grpLevels = ""; grpExitWhy = ""; ArrayResize(grpPos, 0);
  }

void AddPos(ulong id)
  {
   if(id == 0) return;
   for(int k = 0; k < ArraySize(grpPos); k++) if(grpPos[k] == id) return;
   int n = ArraySize(grpPos);
   ArrayResize(grpPos, n + 1); grpPos[n] = id;
  }

// позиция закрылась (стоп, трейлинг, время, застой) — фигура завершена
void CheckGroup()
  {
   if(!grp.on) return;
   ulong tk[];
   int n = OurPositions(tk);
   if(n > 0)
     {
      grp.seenPos = true;
      for(int p = 0; p < n; p++) if(PositionSelectByTicket(tk[p])) AddPos((ulong)PositionGetInteger(POSITION_IDENTIFIER));
      return;
     }
   if(!grp.seenPos && TimeCurrent() - grp.lastFill < 30) return;      // позиция ещё не появилась в списке
   FinishFigure();
   int s = FindSetup(grp.sid);
   ResetGrp();
   SaveState();
   if(s >= 0 && st[s].alive) Kill(s, -1);                               // её неисполненные лимитки снимаются
   UpdateComment();
  }

//+------------------------------------------------------------------+
//| Объём по уровням: Weight618 % на 0,618, остаток поровну.          |
//| Если исполнятся все пять, суммарный убыток по стопу = RiskPercent.|
//| Каждый уровень не меньше минимального лота; если риск выше        |
//| MaxRiskPercent — снимаем уровни, начиная с самого дальнего от     |
//| стопа. Возвращает 0 или код причины пропуска.                     |
//+------------------------------------------------------------------+
int SizeSetup(int s)
  {
   double tickV = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE), tickS = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP), vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double bal  = AccountInfoDouble(ACCOUNT_BALANCE);
   if(tickS <= 0 || tickV <= 0 || step <= 0 || vmin <= 0 || bal <= 0) return(R_VOL);
   double vpu = tickV / tickS;                                          // $ на 1 лот за единицу цены
   double dist[5];
   double denom = 0;
   for(int k = 0; k < 5; k++)
     {
      dist[k] = MathAbs(st[s].lv[k] - st[s].stop);
      if(!st[s].done[k] && st[s].w[k] > 0) denom += st[s].w[k] * dist[k] * vpu;
     }
   if(denom <= 0) return(R_VOL);
   double plan  = bal * RiskPercent / 100.0;
   double total = plan / denom;
   double risk = 0; int cnt = 0;
   for(int k = 0; k < 5; k++)
     {
      st[s].lots[k] = 0;
      if(st[s].done[k] || st[s].w[k] <= 0) continue;                    // уровень уже пройден (поздняя фигура)
      double l = MathFloor(st[s].w[k] * total / step + 1e-9) * step;
      l = MathMin(MathMax(l, vmin), vmax);                              // не меньше минимального лота
      st[s].lots[k] = NormVol(l);
      risk += st[s].lots[k] * dist[k] * vpu;
      cnt++;
     }
   if(cnt == 0) return(R_VOL);
   double before = risk;
   double cap = bal * MaxRiskPercent / 100.0;
   //--- потолок риска: снимаем уровни с самым большим расстоянием до стопа (0,618 — первым), объём не переносим
   while(risk > cap + 1e-9 && cnt > 1)
     {
      int kfar = -1;
      for(int k = 0; k < 5; k++) if(st[s].lots[k] > 0 && (kfar < 0 || dist[k] > dist[kfar])) kfar = k;
      if(kfar < 0) break;
      risk -= st[s].lots[kfar] * dist[kfar] * vpu;
      PrintFormat("Фигура #%d: потолок риска %.1f%% — уровень %s (%.2f лота, риск %.2f $) снят",
                  st[s].id, MaxRiskPercent, LN[kfar], st[s].lots[kfar], st[s].lots[kfar] * dist[kfar] * vpu);
      st[s].lots[kfar] = 0; st[s].done[kfar] = true; cnt--; stat[R_CAPDROP]++;
     }
   if(risk > cap + 1e-9)                                                // остался один уровень — самый близкий к стопу
     {
      int k1 = -1;
      for(int k = 0; k < 5; k++) if(st[s].lots[k] > 0) k1 = k;
      if(k1 < 0) return(R_RISKCAP);
      double l = MathFloor(cap / (dist[k1] * vpu) / step + 1e-9) * step;
      if(l < vmin - 1e-9)
        {
         PrintFormat("Фигура #%d пропущена: даже %.2f лота на %s — риск %.2f $ = %.1f%% баланса, больше потолка %.1f%%",
                     st[s].id, vmin, LN[k1], vmin * dist[k1] * vpu, vmin * dist[k1] * vpu / bal * 100, MaxRiskPercent);
         return(R_RISKCAP);
        }
      st[s].lots[k1] = NormVol(l);
      risk = st[s].lots[k1] * dist[k1] * vpu;
     }
   st[s].planRisk = risk;
   PrintFormat("Объём фигуры #%d: %.2f / %.2f / %.2f / %.2f / %.2f лота (0,618…0,14). Риск: план %.2f $ = %.1f%%; "
               "с мин. лотом %.2f $ = %.1f%%; итог, если исполнятся все, %.2f $ = %.1f%% (потолок %.1f%%)",
               st[s].id, st[s].lots[0], st[s].lots[1], st[s].lots[2], st[s].lots[3], st[s].lots[4],
               plan, RiskPercent, before, before / bal * 100, risk, risk / bal * 100, MaxRiskPercent);
   return(0);
  }

// фигура получает право выставить лимитки
bool Activate(int s)
  {
   if(!LateShift(s)) { Kill(s, R_LATE); return(false); }
   int rc = SizeSetup(s);
   if(rc != 0) { Kill(s, rc); return(false); }
   st[s].sized = true;
   stat[R_ACTIVE]++;
   PrintFormat("Фигура #%d (%s): выставляем лимитки, стоп %s", st[s].id, st[s].buy ? "покупка" : "продажа",
               DoubleToString(st[s].stop, _Digits));
   return(true);
  }

//+------------------------------------------------------------------+
//| Лимитные ордера: выставить, снять, сверить с историей             |
//+------------------------------------------------------------------+
void RefreshHasOrd(int s)
  {
   bool h = false;
   for(int k = 0; k < 5; k++) if(st[s].tk[k] != 0) h = true;
   st[s].hasOrd = h;
  }

bool IsTracked(ulong t)
  {
   for(int s = 0; s < nst; s++)
     {
      if(!st[s].hasOrd) continue;
      for(int k = 0; k < 5; k++) if(st[s].tk[k] == t) return(true);
     }
   return(false);
  }

// есть ли наши лимитки, которые НЕ принадлежат фигуре s (на неттинге две фигуры не должны исполниться разом)
bool OtherOrdersExist(int s)
  {
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong t = OrderGetTicket(i);
      if(t == 0) continue;
      if(OrderGetString(ORDER_SYMBOL) != _Symbol || OrderGetInteger(ORDER_MAGIC) != Magic) continue;
      bool own = false;
      for(int k = 0; k < 5; k++) if(st[s].tk[k] == t) own = true;
      if(!own) return(true);
     }
   return(false);
  }

bool SendLimit(bool buy, double vol, double p, double sl, ENUM_ORDER_TYPE_TIME tt, string cm)
  {
   bool ok = buy ? trade.BuyLimit(vol, p, _Symbol, sl, 0.0, tt, 0, cm) : trade.SellLimit(vol, p, _Symbol, sl, 0.0, tt, 0, cm);
   uint rc = trade.ResultRetcode();
   if(rc == TRADE_RETCODE_INVALID_FILL)                                 // брокер не принял тип заполнения — пробуем «Возврат»
     {
      trade.SetTypeFilling(ORDER_FILLING_RETURN);
      ok = buy ? trade.BuyLimit(vol, p, _Symbol, sl, 0.0, tt, 0, cm) : trade.SellLimit(vol, p, _Symbol, sl, 0.0, tt, 0, cm);
      rc = trade.ResultRetcode();
      trade.SetTypeFillingBySymbol(_Symbol);
     }
   return(ok && (rc == TRADE_RETCODE_DONE || rc == TRADE_RETCODE_PLACED) && trade.ResultOrder() > 0);
  }

// выставить недостающие лимитки фигуры s
void PlaceLevels(int s)
  {
   bool need = false;
   for(int k = 0; k < 5; k++) if(!st[s].done[k] && st[s].tk[k] == 0 && st[s].lots[k] > 0) need = true;
   if(!need || !CanTrade()) return;
   if(OtherOrdersExist(s)) return;                                      // сначала должны сняться лимитки другой фигуры
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID), ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double minD = MinDist();
   ENUM_ORDER_TYPE_TIME tt = TimeMode();
   bool buy = st[s].buy;
   for(int k = 0; k < 5; k++)
     {
      if(st[s].done[k] || st[s].tk[k] != 0 || st[s].lots[k] <= 0) continue;
      if(TimeCurrent() - st[s].lastTry[k] < 10) continue;               // после ошибки — пауза 10 секунд
      double vol = NormVol(st[s].lots[k] - st[s].got[k]);
      if(vol < vmin - 1e-9) { st[s].done[k] = true; continue; }
      //--- цена уже прошла уровень, а ордера не было (новости, сбой) — уровень пропущен, по рынку не входим
      if(buy ? ask <= st[s].lv[k] : bid >= st[s].lv[k])
        {
         st[s].done[k] = true;
         stat[st[s].newsOff[k] ? R_NEWS : R_MISSED]++;
         PrintFormat("Фигура #%d: уровень %s пройден, когда лимитки не было (%s) — пропущен",
                     st[s].id, LN[k], st[s].newsOff[k] ? "новости" : "ордер не стоял");
         continue;
        }
      //--- уровень слишком близко к цене: ставим на минимально допустимом расстоянии (вход чуть глубже)
      double p = st[s].lv[k];
      bool adj = false;
      if(buy  && p > ask - minD) { p = ask - minD; adj = true; }
      if(!buy && p < bid + minD) { p = bid + minD; adj = true; }
      p = buy ? PriceDown(p) : PriceUp(p);
      double sl = NormPrice(st[s].stop);
      bool slBad = buy ? (sl >= p || p - sl < minD) : (sl <= p || sl - p < minD);
      if(slBad)
        {
         st[s].done[k] = true; stat[R_SKIPSTOP]++;
         PrintFormat("Фигура #%d: уровень %s пропущен — стоп %s ближе к цене входа %s, чем разрешает брокер (%s)",
                     st[s].id, LN[k], DoubleToString(sl, _Digits), DoubleToString(p, _Digits), DoubleToString(minD, _Digits));
         continue;
        }
      if(adj)
         PrintFormat("Фигура #%d: уровень %s (%s) ближе к цене, чем разрешает брокер, — лимитка на %s",
                     st[s].id, LN[k], DoubleToString(st[s].lv[k], _Digits), DoubleToString(p, _Digits));
      string cm = "B1 Z " + LN[k] + " #" + IntegerToString(st[s].id);
      st[s].lastTry[k] = TimeCurrent();
      if(SendLimit(buy, vol, p, sl, tt, cm))
        {
         st[s].tk[k] = trade.ResultOrder(); st[s].px[k] = p; st[s].sent[k] = vol; st[s].gotOrd[k] = 0;
         st[s].delByUs[k] = false; st[s].miss[k] = 0; st[s].hasOrd = true;
         PrintFormat("Лимитка %s %s фигуры #%d: %.2f лота по %s, стоп %s, ордер %s", buy ? "BuyLimit" : "SellLimit", LN[k], st[s].id,
                     vol, DoubleToString(p, _Digits), DoubleToString(sl, _Digits), IntegerToString((long)st[s].tk[k]));
         st[s].newsOff[k] = false;
        }
      else
        {
         st[s].fails[k]++;
         PrintFormat("Лимитка %s фигуры #%d не выставлена (попытка %d из 5): %d %s", LN[k], st[s].id, st[s].fails[k],
                     trade.ResultRetcode(), trade.ResultRetcodeDescription());
         if(st[s].fails[k] >= 5) { st[s].done[k] = true; stat[R_ORDFAIL]++; }
        }
     }
  }

// цена исполнения ордера по сделкам (если сделки не нашлись — цена ордера)
double DealPrice(ulong ot, double def)
  {
   if(!HistorySelect(TimeCurrent() - 7 * 86400, TimeCurrent() + 86400)) return(def);
   double v = 0, pv = 0;
   for(int i = HistoryDealsTotal() - 1; i >= 0; i--)
     {
      ulong d = HistoryDealGetTicket(i);
      if(d == 0) continue;
      if((ulong)HistoryDealGetInteger(d, DEAL_ORDER) != ot) continue;
      double dv = HistoryDealGetDouble(d, DEAL_VOLUME);
      v += dv; pv += dv * HistoryDealGetDouble(d, DEAL_PRICE);
     }
   return(v > 0 ? pv / v : def);
  }

// сверить лимитку уровня k фигуры s: стоит / исполнилась (целиком или частично) / снята
void SyncLevel(int s, int k)
  {
   ulong t = st[s].tk[k];
   if(t == 0) return;
   if(OrderSelect(t))                                                   // ещё стоит; возможно, исполнена частично
     {
      double f = st[s].sent[k] - OrderGetDouble(ORDER_VOLUME_CURRENT);
      if(f > st[s].gotOrd[k] + 1e-9)
        {
         double d = f - st[s].gotOrd[k];
         st[s].gotOrd[k] = f;
         RegisterFill(s, k, d, DealPrice(t, OrderGetDouble(ORDER_PRICE_OPEN)), 0);
        }
      st[s].miss[k] = 0;
      return;
     }
   if(!HistoryOrderSelect(t))                                           // ордера нет ни среди действующих, ни в истории — ждём
     {
      if(++st[s].miss[k] >= 100)
        {
         PrintFormat("Лимитка %s фигуры #%d (ордер %s) не найдена ни в терминале, ни в истории — считаем снятой",
                     LN[k], st[s].id, IntegerToString((long)t));
         st[s].tk[k] = 0; st[s].miss[k] = 0; st[s].gotOrd[k] = 0; st[s].sent[k] = 0;
         RefreshHasOrd(s);
        }
      return;
     }
   long   state = HistoryOrderGetInteger(t, ORDER_STATE);
   double vi    = HistoryOrderGetDouble(t, ORDER_VOLUME_INITIAL);
   double vc    = HistoryOrderGetDouble(t, ORDER_VOLUME_CURRENT);
   double opx   = HistoryOrderGetDouble(t, ORDER_PRICE_OPEN);
   ulong  pid   = (ulong)HistoryOrderGetInteger(t, ORDER_POSITION_ID);
   double f = MathMax(0.0, vi - vc);
   if(state == ORDER_STATE_FILLED) f = vi;
   st[s].tk[k] = 0; st[s].miss[k] = 0;
   if(f > st[s].gotOrd[k] + 1e-9)
      RegisterFill(s, k, f - st[s].gotOrd[k], DealPrice(t, opx), pid);
   else if(!st[s].delByUs[k] && state != ORDER_STATE_EXPIRED)
     {
      st[s].fails[k]++;
      PrintFormat("Лимитка %s фигуры #%d снята не советником (состояние %d), попытка %d из 5",
                  LN[k], st[s].id, (int)state, st[s].fails[k]);
      if(st[s].fails[k] >= 5) { st[s].done[k] = true; stat[R_ORDFAIL]++; }
     }
   st[s].gotOrd[k] = 0; st[s].sent[k] = 0; st[s].delByUs[k] = false;
   if(st[s].got[k] >= st[s].lots[k] - 1e-9) st[s].done[k] = true;      // уровень исполнен полностью
   RefreshHasOrd(s);
  }

void SyncAll()
  {
   for(int s = 0; s < nst; s++)
     {
      if(!st[s].hasOrd) continue;
      for(int k = 0; k < 5; k++) if(st[s].tk[k] != 0) SyncLevel(s, k);
     }
  }

// снять лимитку уровня k; true — ордера больше нет
bool DeleteLevel(int s, int k)
  {
   ulong t = st[s].tk[k];
   if(t == 0) return(true);
   if(!OrderSelect(t)) { SyncLevel(s, k); return(st[s].tk[k] == 0); }  // уже исполнилась или снята — учесть
   if(!CanTrade()) return(false);
   if(TimeCurrent() - st[s].lastTry[k] < 10 && st[s].delByUs[k]) return(false);   // недавно не вышло — пауза
   st[s].lastTry[k] = TimeCurrent();
   st[s].delByUs[k] = true;
   bool ok = trade.OrderDelete(t);
   uint rc = trade.ResultRetcode();
   if(!ok || (rc != TRADE_RETCODE_DONE && rc != TRADE_RETCODE_PLACED))
     {
      PrintFormat("Не удалось снять лимитку %s фигуры #%d: %d %s (повтор позже)", LN[k], st[s].id, rc, trade.ResultRetcodeDescription());
      return(false);
     }
   PrintFormat("Лимитка %s фигуры #%d снята", LN[k], st[s].id);
   SyncLevel(s, k);                                                     // учесть частичное исполнение до снятия
   return(true);
  }

bool DeleteSetupOrders(int s)
  {
   if(!st[s].hasOrd) return(true);
   bool ok = true;
   for(int k = 0; k < 5; k++) if(st[s].tk[k] != 0 && !DeleteLevel(s, k)) ok = false;
   RefreshHasOrd(s);
   return(ok);
  }

// все наши отложенные ордера по символу (запуск/остановка советника)
void DeleteAllOurOrders(string why)
  {
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong t = OrderGetTicket(i);
      if(t == 0) continue;
      if(OrderGetString(ORDER_SYMBOL) != _Symbol || OrderGetInteger(ORDER_MAGIC) != Magic) continue;
      string cm = OrderGetString(ORDER_COMMENT);
      if(trade.OrderDelete(t)) PrintFormat("%s: ордер %s (%s)", why, IntegerToString((long)t), cm);
      else PrintFormat("Не удалось снять ордер %s (%s): %d", IntegerToString((long)t), cm, trade.ResultRetcode());
     }
   for(int s = 0; s < nst; s++) if(st[s].hasOrd) { for(int k = 0; k < 5; k++) SyncLevel(s, k); }
  }

// наши ордера, которых советник не знает (остались после сбоя), — снять
void CleanOrphans()
  {
   if(!CanTrade()) return;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong t = OrderGetTicket(i);
      if(t == 0) continue;
      if(OrderGetString(ORDER_SYMBOL) != _Symbol || OrderGetInteger(ORDER_MAGIC) != Magic) continue;
      if(IsTracked(t)) continue;
      string cm = OrderGetString(ORDER_COMMENT);
      if(trade.OrderDelete(t)) PrintFormat("Снят «потерянный» ордер %s (%s)", IntegerToString((long)t), cm);
     }
  }

//+------------------------------------------------------------------+
//| Исполнение лимитки: объём vol по цене price                       |
//+------------------------------------------------------------------+
void RegisterFill(int s, int k, double vol, double price, ulong pid)
  {
   if(vol <= 1e-9) return;
   bool buy = st[s].buy;
   bool wasOn = grp.on;
   if(!grp.on)
     {
      ResetGrp();
      grp.on = true; grp.sid = st[s].id; grp.buy = buy; grp.B = st[s].B; grp.target1 = st[s].target1;
      grp.stop0 = st[s].stop; grp.slWant = NormPrice(st[s].stop); grp.planRisk = st[s].planRisk;
      grp.opened = TimeCurrent(); grp.ext = price; grp.lastExtH1 = NH;
      if(!st[s].any) { stat[R_TRADES]++; if(DrawObjects) DrawSetup(s); }
     }
   else if(grp.sid != st[s].id)
      PrintFormat("ВНИМАНИЕ: исполнилась лимитка фигуры #%d, а позиция открыта по фигуре #%d — объём добавлен к позиции, стоп вернём на место",
                  st[s].id, grp.sid);
   st[s].any = true;
   AddPos(pid);
   if(st[s].got[k] <= 1e-9) { stat[R_FILLS]++; grpLevels += (grpLevels == "" ? "" : "+") + LN[k]; }
   st[s].got[k] += vol;
   grp.initVol += vol;
   //--- позиция выросла: максимум прибыли для «застоя» считаем заново от этой цены
   grp.ext = price; grp.lastExtH1 = NH; grp.lastFill = TimeCurrent();
   PrintFormat("ВХОД %s %s на %s (фигура #%d): цена %s, лоты %.2f, стоп %s, цель %s, A=%s B=%s",
               buy ? "ПОКУПКА" : "ПРОДАЖА", _Symbol, LN[k], st[s].id, DoubleToString(price, _Digits), vol,
               DoubleToString(st[s].stop, _Digits), DoubleToString(st[s].target1, _Digits),
               DoubleToString(st[s].A, _Digits), DoubleToString(st[s].B, _Digits));
   if(wasOn) FixSL(false);                                              // на неттинге новая сделка могла поменять стоп позиции
   SaveState();
   UpdateComment();
  }

//+------------------------------------------------------------------+
//| На каждом тике: снять / заменить / выставить лимитки              |
//+------------------------------------------------------------------+
int FirstOpenLevel(int s)
  {
   for(int k = 0; k < 5; k++) if(!st[s].done[k] && st[s].w[k] > 0) return(k);
   return(-1);
  }

int NewestAlive()
  {
   for(int s = nst - 1; s >= 0; s--) if(st[s].alive) return(s);
   return(-1);
  }

// фигура, которой сейчас разрешено держать лимитки
bool Eligible(int s)
  {
   if(!st[s].alive || !st[s].sized) return(false);
   if(grp.on) return(grp.sid == st[s].id);
   return(st[s].id == actSid);
  }

void ManageSetups()
  {
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID), ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   if(bid <= 0 || ask <= 0) return;
   //--- 1) снятие фигур
   for(int s = 0; s < nst; s++)
     {
      if(!st[s].alive) continue;
      bool buy  = st[s].buy;
      bool mine = grp.on && grp.sid == st[s].id;
      //--- цена ушла за B — неисполненные лимитки снимаются
      if(buy ? bid >= st[s].B : bid <= st[s].B) { Kill(s, st[s].any ? -1 : R_GONE); continue; }
      //--- позиция по фигуре уже закрыта (стоп, время, застой) — остальные лимитки не нужны
      if(st[s].any && !mine) { Kill(s, -1); continue; }
      //--- стоп задет раньше, чем исполнилась хоть одна лимитка (гэп)
      if(!st[s].any && (buy ? bid <= st[s].stop : ask >= st[s].stop)) { Kill(s, R_STOPFIRST); continue; }
      //--- открыта позиция по другой фигуре: эта ждёт без ордеров; цена коснулась её уровня — пропуск (как в v1.29)
      if(grp.on && !mine)
        {
         if(st[s].hasOrd) DeleteSetupOrders(s);
         int k = FirstOpenLevel(s);
         if(k >= 0 && (buy ? ask <= st[s].lv[k] : bid >= st[s].lv[k])) Kill(s, R_BUSY);
        }
     }
   //--- 2) новости: лимитки снимаем, уровни, которых цена коснулась в окне, пропускаем
   if(newsNow)
      for(int s = 0; s < nst; s++)
        {
         if(st[s].hasOrd)
            for(int k = 0; k < 5; k++)
               if(st[s].tk[k] != 0 && DeleteLevel(s, k) && !st[s].done[k]) st[s].newsOff[k] = true;
         if(!Eligible(s)) continue;
         for(int k = 0; k < 5; k++)
           {
            if(st[s].done[k] || st[s].tk[k] != 0 || st[s].lots[k] <= 0) continue;
            if(st[s].buy ? ask <= st[s].lv[k] : bid >= st[s].lv[k])
              {
               st[s].done[k] = true; st[s].newsOff[k] = false; stat[R_NEWS]++;
               PrintFormat("Фигура #%d: лимитка %s пропущена — новости ±%d мин", st[s].id, LN[k], NewsWindowMin);
              }
           }
        }
   //--- 3) позиции нет: лимитки только у самой новой живой фигуры, старые неисполненные снимаются
   if(!grp.on)
      for(int guard = 0; guard < 50; guard++)
        {
         int t = NewestAlive();
         if(t < 0 || st[t].id == actSid) break;
         if(!Activate(t)) continue;                                     // Activate сам снял фигуру с причиной
         actSid = st[t].id;
         for(int s = 0; s < nst; s++)
            if(s != t && st[s].alive) Kill(s, R_REPLACED);
         break;
        }
   //--- 4) лимитки снятых фигур, которые не удалось снять раньше
   for(int s = 0; s < nst; s++)
      if(st[s].hasOrd && !Eligible(s)) DeleteSetupOrders(s);
   //--- 5) выставить недостающие лимитки
   if(!newsNow)
     {
      int s = grp.on ? FindSetup(grp.sid) : FindSetup(actSid);
      if(s >= 0 && Eligible(s)) PlaceLevels(s);
     }
  }

//+------------------------------------------------------------------+
//| Закрытие части позиции и всей позиции.                           |
//| CTrade::PositionClosePartial(тикет) работает ТОЛЬКО на хеджинге:  |
//| на неттинговом счёте часть закрываем встречной сделкой нужного    |
//| объёма. Встречная сделка — рыночная, её тикет не совпадает ни с   |
//| одной лимиткой, поэтому за исполнение лимитки она не считается.   |
//| Объём никогда не больше позиции — разворота не будет.             |
//+------------------------------------------------------------------+
bool ClosePart(ulong tk, double vol, string why, double &closed)
  {
   closed = 0;
   if(!PositionSelectByTicket(tk)) return(false);
   bool isBuy = PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY;
   double sl = PositionGetDouble(POSITION_SL);
   double pv = PositionGetDouble(POSITION_VOLUME);
   vol = NormVol(vol);
   if(vol <= 0) return(false);
   if(vol >= pv - 1e-9) { bool r = CloseWhole(tk, why); if(r) closed = pv; return(r); }
   bool ok;
   if(IsHedge()) ok = trade.PositionClosePartial(tk, vol);
   else          ok = isBuy ? trade.Sell(vol, _Symbol, 0, 0, 0, "B1 " + why) : trade.Buy(vol, _Symbol, 0, 0, 0, "B1 " + why);
   ok = ok && RcOk();
   if(!ok) { PrintFormat("%s: не удалось закрыть %.2f лота, код %d", why, vol, trade.ResultRetcode()); return(false); }
   closed = trade.ResultVolume();
   if(closed <= 0) closed = vol;
   // на неттинге встречная сделка может сбросить стоп позиции — возвращаем его
   if(sl > 0 && PositionSelectByTicket(tk) && MathAbs(PositionGetDouble(POSITION_SL) - sl) > _Point / 2)
      trade.PositionModify(tk, sl, 0);
   PrintFormat("%s: закрыто %.2f лота по %s", why, closed, DoubleToString(trade.ResultPrice(), _Digits));
   return(true);
  }

bool CloseWhole(ulong tk, string why)
  {
   bool ok = IsHedge() ? trade.PositionClose(tk) : trade.PositionClose(_Symbol);
   ok = ok && RcOk();
   PrintFormat("%s: %s", why, ok ? "позиция закрыта" : "не удалось закрыть позицию");
   return(ok);
  }

// стоп в безубыток с учётом издержек (спред + BEExtraPoints); true — стоп уже там или перенесён
bool MoveToBE(ulong tk, string why)
  {
   if(!PositionSelectByTicket(tk)) return(false);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID), ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double minD = MinDist();
   double cost = (ask - bid) + BEExtraPoints * _Point;
   double open = PositionGetDouble(POSITION_PRICE_OPEN), cur = PositionGetDouble(POSITION_SL);
   double be = grp.buy ? PriceUp(open + cost) : PriceDown(open - cost);
   bool better = grp.buy ? be > cur + _Point / 2 : (cur == 0 || be < cur - _Point / 2);
   if(!better) return(true);
   bool valid = grp.buy ? be < bid - minD : be > ask + minD;
   if(!valid) return(false);                                             // цена слишком близко — повтор на следующем тике
   if(!trade.PositionModify(tk, be, 0)) { PrintFormat("%s: не удалось перенести стоп, код %d", why, trade.ResultRetcode()); return(false); }
   grp.slWant = be;
   PrintFormat("%s: стоп в безубыток %s (вход %s + издержки)", why, DoubleToString(be, _Digits), DoubleToString(open, _Digits));
   return(true);
  }

// стоп позиции не на месте (на неттинге его могла сбросить/поменять новая сделка) — вернуть
void FixSL(bool onlyZero)
  {
   if(!grp.on || grp.slWant <= 0) return;
   ulong tk[];
   int n = OurPositions(tk);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID), ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double minD = MinDist();
   for(int p = 0; p < n; p++)
     {
      if(!PositionSelectByTicket(tk[p])) continue;
      double cur = PositionGetDouble(POSITION_SL);
      if(onlyZero && cur > 0) continue;
      if(MathAbs(cur - grp.slWant) <= _Point / 2) continue;
      bool valid = grp.buy ? grp.slWant < bid - minD : grp.slWant > ask + minD;
      if(!valid)
        {
         if(cur == 0)                                                    // стопа нет, а цена уже за ним — выходим
           {
            Print("Позиция без стопа, а цена уже за уровнем стопа — закрываем");
            if(CloseWhole(tk[p], "Стоп (позиция была без стопа)")) grpExitWhy = "стоп";
           }
         continue;
        }
      if(trade.PositionModify(tk[p], grp.slWant, PositionGetDouble(POSITION_TP)))
         PrintFormat("Стоп позиции возвращён на %s", DoubleToString(grp.slWant, _Digits));
     }
  }

// закрыть pct % НАЧАЛЬНОГО объёма фигуры; true — закрыто (или закрывать нечего)
bool CloseShare(double pct, string why)
  {
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP), vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   if(step <= 0) return(false);
   ulong tk[];
   int n = OurPositions(tk);
   double total = 0;
   for(int p = 0; p < n; p++) if(PositionSelectByTicket(tk[p])) total += PositionGetDouble(POSITION_VOLUME);
   if(total <= 0) return(true);
   double want = NormVol(MathRound(grp.initVol * pct / 100.0 / step) * step);
   if(want < vmin - 1e-9) want = vmin;                                   // мелкая позиция: закрываем хотя бы минимальный лот
   if(total < 2 * vmin - 1e-9) { PrintFormat("%s: позиция %.2f лота, делить нечего — оставляем целиком", why, total); return(true); }
   bool ok = true;
   if(total - want < vmin - 1e-9)                                      // остаток меньше минимального лота — закрываем всё
     {
      for(int p = 0; p < n; p++) if(!CloseWhole(tk[p], why)) ok = false;
      return(ok);
     }
   for(int p = 0; p < n && want >= vmin - 1e-9; p++)
     {
      if(!PositionSelectByTicket(tk[p])) continue;
      double v = PositionGetDouble(POSITION_VOLUME);
      double c = MathMin(v, want);
      if(v - c > 1e-9 && v - c < vmin) c = v - vmin;                     // не оставлять на тикете меньше минимума
      c = NormVol(c);
      if(c < vmin - 1e-9) continue;
      if(c >= v - 1e-9)
        {
         if(CloseWhole(tk[p], why)) want -= c; else ok = false;
        }
      else
        {
         double got = 0;
         if(ClosePart(tk[p], c, why, got)) want -= got; else ok = false;
        }
     }
   return(ok);
  }

// средняя цена входа и общий объём открытых позиций бота
double AvgOpen(double &vol)
  {
   ulong tk[];
   int n = OurPositions(tk);
   double sum = 0; vol = 0;
   for(int p = 0; p < n; p++)
      if(PositionSelectByTicket(tk[p])) { double v = PositionGetDouble(POSITION_VOLUME); vol += v; sum += v * PositionGetDouble(POSITION_PRICE_OPEN); }
   return(vol > 0 ? sum / vol : 0);
  }

bool GroupHasOrders()
  {
   int s = FindSetup(grp.sid);
   return(s >= 0 && st[s].hasOrd);
  }

//+------------------------------------------------------------------+
//| На каждом тике: цена ушла за B — закрыть PartialAtB % начального  |
//| объёма и стоп в безубыток с учётом издержек. Трейлинга ещё нет.   |
//+------------------------------------------------------------------+
void CheckBreakeven()
  {
   if(!grp.on || grp.beDone || (!BreakevenAtB && PartialAtB <= 0)) return;
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if(grp.buy ? bid < grp.B : bid > grp.B) return;                      // цена ещё не за B
   if(GroupHasOrders()) return;                                         // сначала должны сняться лимитки (встречная сделка — без них)
   bool ok = true;
   if(PartialAtB > 0 && !grp.partDone)
     {
      if(CloseShare(PartialAtB, "Цена ушла за B")) grp.partDone = true;  // флаг — только после успешного закрытия
      else ok = false;
     }
   if(BreakevenAtB)
     {
      ulong tk[];
      int n = OurPositions(tk);
      for(int p = 0; p < n; p++) if(!MoveToBE(tk[p], "Цена ушла за B")) ok = false;
     }
   if(ok) { grp.beDone = true; stat[R_BE]++; SaveState(); }
  }

//+------------------------------------------------------------------+
//| На каждом тике: цена дошла до цели — закрыть TargetPart %         |
//| начального объёма; дальше остаток сопровождает трейлинг.          |
//+------------------------------------------------------------------+
void CheckTargets()
  {
   if(!grp.on || grp.tpDone || grp.target1 <= 0) return;
   double px = grp.buy ? SymbolInfoDouble(_Symbol, SYMBOL_BID) : SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   if(grp.buy ? px < grp.target1 : px > grp.target1) return;
   if(GroupHasOrders()) return;
   if(!CloseShare(TargetPart, "Цель")) return;                           // не вышло — повтор на следующем тике
   ulong tk[];
   int n = OurPositions(tk);
   for(int p = 0; p < n; p++) MoveToBE(tk[p], "Цель");
   grp.tpDone = true;
   SaveState();
   Print("Цель: включён трейлинг остатка");
  }

// снять лимитки фигуры, по которой открыта позиция (перед полным выходом)
void DeleteGroupOrders()
  {
   int s = FindSetup(grp.sid);
   if(s < 0) return;
   if(st[s].alive) Kill(s, -1); else DeleteSetupOrders(s);
  }

//+------------------------------------------------------------------+
//| На закрытии 15-минутки: экстремум, выход по времени, застой,      |
//| трейлинг (только после цели).                                    |
//+------------------------------------------------------------------+
void ManageTrades()
  {
   if(!grp.on) return;
   MqlRates m[];
   if(CopyRates(_Symbol, PERIOD_M15, 1, 1, m) != 1) return;
   double ne = grp.buy ? MathMax(grp.ext, m[0].high) : MathMin(grp.ext, m[0].low);
   if(grp.buy ? ne > grp.ext + _Point / 2 : ne < grp.ext - _Point / 2) grp.lastExtH1 = NH;   // новый благоприятный экстремум
   grp.ext = ne;
   ulong tk[];
   int n = OurPositions(tk);
   if(n == 0) return;
   if(TimeCurrent() - grp.opened >= MaxHoldDays * 86400)
     {
      DeleteGroupOrders();
      bool ok = true;
      for(int p = 0; p < n; p++) if(!CloseWhole(tk[p], "Выход по времени")) ok = false;
      if(ok) grpExitWhy = "время (" + IntegerToString(MaxHoldDays) + " дн.)";
      return;
     }
   double px = grp.buy ? SymbolInfoDouble(_Symbol, SYMBOL_BID) : SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   //--- застой после прибыли: был ≥ StagMinR, StagBars H1-свечей без нового экстремума, отдано ≥ StagGiveBack %, ещё ≥ StagMinCurR
   if(StagBars > 0)
     {
      double vol = 0, avg = AvgOpen(vol), risk = (grp.stop0 > 0) ? MathAbs(avg - grp.stop0) : 0;
      if(vol > 0 && risk > 0)
        {
         double dir = grp.buy ? 1.0 : -1.0;
         double curR = (px - avg) * dir / risk, maxR = (grp.ext - avg) * dir / risk;
         if(maxR >= StagMinR && NH - grp.lastExtH1 >= StagBars && maxR - curR >= StagGiveBack / 100.0 * maxR && curR >= StagMinCurR)
           {
            DeleteGroupOrders();
            bool ok = true;
            for(int p = 0; p < n; p++) if(!CloseWhole(tk[p], StringFormat("Застой: было +%.2fR, сейчас +%.2fR", maxR, curR))) ok = false;
            if(ok) { stat[R_STAG]++; grpExitWhy = "застой"; }
            return;
           }
        }
     }
   if(!grp.tpDone) return;                                               // трейлинг — только после цели
   double atr = (NH > 0) ? ATR[NH - 1] : 0;
   if(atr <= 0) return;
   double minD = MinDist();
   double cand = grp.buy ? grp.ext - TrailATRMult * atr : grp.ext + TrailATRMult * atr;
   for(int p = 0; p < n; p++)
     {
      if(!PositionSelectByTicket(tk[p])) continue;
      double cur = PositionGetDouble(POSITION_SL);
      double nsl = grp.buy ? MathMax(cur, cand) : MathMin(cur > 0 ? cur : DBL_MAX, cand);
      nsl = grp.buy ? PriceDown(nsl) : PriceUp(nsl);
      bool better = grp.buy ? nsl > cur + _Point : (cur == 0 || nsl < cur - _Point);
      bool valid  = grp.buy ? nsl < px - minD : nsl > px + minD;
      if(better && valid && trade.PositionModify(tk[p], nsl, 0))
        {
         grp.slWant = nsl;
         PrintFormat("Трейлинг: стоп %s", DoubleToString(nsl, _Digits));
        }
     }
  }

//+------------------------------------------------------------------+
//| Состояние позиции — в глобальных переменных терминала, чтобы      |
//| после перезапуска советника сопровождать её так же                |
//+------------------------------------------------------------------+
string GVName(string key) { return("B1Z_" + _Symbol + "_" + IntegerToString(Magic) + "_" + key); }
double GVGet(string key)  { string nm = GVName(key); return(GlobalVariableCheck(nm) ? GlobalVariableGet(nm) : 0.0); }
void   GVSet(string key, double v) { GlobalVariableSet(GVName(key), v); }

void SaveState()
  {
   if(!grp.on) { GVSet("on", 0); return; }
   GVSet("on", 1);
   GVSet("pid", ArraySize(grpPos) > 0 ? (double)grpPos[0] : 0.0);
   GVSet("buy", grp.buy ? 1 : 0);
   GVSet("B", grp.B); GVSet("tgt", grp.target1); GVSet("stop0", grp.stop0); GVSet("initVol", grp.initVol);
   GVSet("be", grp.beDone ? 1 : 0); GVSet("part", grp.partDone ? 1 : 0); GVSet("tp", grp.tpDone ? 1 : 0);
   GVSet("opened", (double)grp.opened); GVSet("ext", grp.ext); GVSet("risk", grp.planRisk); GVSet("slw", grp.slWant);
  }

// первый тик после запуска: есть позиция бота — восстановить сопровождение
void RestoreGroup()
  {
   ulong tk[];
   int n = OurPositions(tk);
   if(n == 0) { GVSet("on", 0); return; }
   ResetGrp();
   if(!PositionSelectByTicket(tk[0])) return;
   bool buy = PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY;
   double sl0 = PositionGetDouble(POSITION_SL);
   datetime t0 = (datetime)PositionGetInteger(POSITION_TIME);
   double vol = 0, avg = AvgOpen(vol);
   bool match = false;
   if(GVGet("on") > 0.5)
     {
      ulong pid = (ulong)GVGet("pid");
      for(int p = 0; p < n; p++)
         if(PositionSelectByTicket(tk[p]) && (ulong)PositionGetInteger(POSITION_IDENTIFIER) == pid) match = true;
      if((GVGet("buy") > 0.5) != buy) match = false;
     }
   grp.on = true; grp.sid = -1; grp.buy = buy;
   if(match)
     {
      grp.B = GVGet("B"); grp.target1 = GVGet("tgt"); grp.stop0 = GVGet("stop0"); grp.initVol = GVGet("initVol");
      grp.beDone = GVGet("be") > 0.5; grp.partDone = GVGet("part") > 0.5; grp.tpDone = GVGet("tp") > 0.5;
      grp.opened = (datetime)GVGet("opened"); grp.ext = GVGet("ext"); grp.planRisk = GVGet("risk"); grp.slWant = GVGet("slw");
      grpLevels = "восстановлена";
      PrintFormat("Найдена позиция бота %.2f лота — состояние восстановлено, сопровождение продолжается", vol);
     }
   else
     {
      //--- состояния нет: сопровождаем осторожно — стоп как есть, трейлинг 3 ATR, выход по времени
      grp.B = avg; grp.target1 = 0; grp.stop0 = sl0; grp.initVol = vol;
      grp.beDone = true; grp.partDone = true; grp.tpDone = true;
      grp.opened = t0; grp.ext = avg; grp.slWant = sl0; grp.planRisk = 0;
      double tickV = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE), tickS = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
      if(sl0 > 0 && tickS > 0) grp.planRisk = vol * MathAbs(avg - sl0) / tickS * tickV;
      grpLevels = "чужая/без состояния";
      PrintFormat("ВНИМАНИЕ: найдена позиция бота %.2f лота без сохранённого состояния — сопровождаю только стопом, трейлингом %.1f ATR и выходом по времени",
                  vol, TrailATRMult);
     }
   grp.lastExtH1 = NH; grp.seenPos = true; grp.lastFill = TimeCurrent();
   for(int p = 0; p < n; p++) if(PositionSelectByTicket(tk[p])) AddPos((ulong)PositionGetInteger(POSITION_IDENTIFIER));
   SaveState();
  }

//+------------------------------------------------------------------+
//| Отчёт: строка в CSV на каждую закрытую фигуру, итоги месяца       |
//+------------------------------------------------------------------+
string CsvName() { return("b1_zigzag_" + _Symbol + (MQLInfoInteger(MQL_TESTER) != 0 ? "_tester" : "") + "_trades.csv"); }

string Num(double v, int d) { string s = DoubleToString(v, d); StringReplace(s, ".", ","); return(s); }   // запятая — для русского Excel
double ParseNum(string s)   { string t = s; StringReplace(t, ",", "."); StringTrimLeft(t); StringTrimRight(t); return(StringToDouble(t)); }

void WriteCsv(string line)
  {
   int h = FileOpen(CsvName(), FILE_READ | FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON | FILE_SHARE_READ, '\t', CP_UTF8);
   if(h == INVALID_HANDLE) { PrintFormat("Не удалось открыть файл отчёта %s, ошибка %d", CsvName(), GetLastError()); return; }
   if(FileSize(h) == 0)
      FileWriteString(h, ShortToString((ushort)0xFEFF) + "открытие;закрытие;символ;направление;уровни;объём;прибыль $;прибыль R;баланс после;причина выхода\r\n");
   FileSeek(h, 0, SEEK_END);
   FileWriteString(h, line + "\r\n");
   FileClose(h);
  }

void FinishFigure()
  {
   double pnl = 0;
   datetime lastT = 0;
   long lastReason = -1;
   int nd = 0;
   for(int p = 0; p < ArraySize(grpPos); p++)
     {
      if(!HistorySelectByPosition((long)grpPos[p])) continue;
      for(int i = 0; i < HistoryDealsTotal(); i++)
        {
         ulong d = HistoryDealGetTicket(i);
         if(d == 0) continue;
         pnl += HistoryDealGetDouble(d, DEAL_PROFIT) + HistoryDealGetDouble(d, DEAL_COMMISSION) + HistoryDealGetDouble(d, DEAL_SWAP);
         nd++;
         long en = HistoryDealGetInteger(d, DEAL_ENTRY);
         datetime dt = (datetime)HistoryDealGetInteger(d, DEAL_TIME);
         if((en == DEAL_ENTRY_OUT || en == DEAL_ENTRY_INOUT || en == DEAL_ENTRY_OUT_BY) && dt >= lastT)
           { lastT = dt; lastReason = HistoryDealGetInteger(d, DEAL_REASON); }
        }
     }
   if(nd == 0 && HistorySelect(grp.opened - 60, TimeCurrent() + 60))   // запасной путь: сделки по символу и magic
      for(int i = 0; i < HistoryDealsTotal(); i++)
        {
         ulong d = HistoryDealGetTicket(i);
         if(d == 0) continue;
         if(HistoryDealGetString(d, DEAL_SYMBOL) != _Symbol || HistoryDealGetInteger(d, DEAL_MAGIC) != Magic) continue;
         pnl += HistoryDealGetDouble(d, DEAL_PROFIT) + HistoryDealGetDouble(d, DEAL_COMMISSION) + HistoryDealGetDouble(d, DEAL_SWAP);
         datetime dt = (datetime)HistoryDealGetInteger(d, DEAL_TIME);
         if(dt >= lastT) { lastT = dt; lastReason = HistoryDealGetInteger(d, DEAL_REASON); }
        }
   datetime tClose = (lastT > 0) ? lastT : TimeCurrent();
   string why = grpExitWhy;
   if(why == "")
     {
      if(lastReason == DEAL_REASON_SL) why = grp.tpDone ? "трейлинг-стоп" : (grp.beDone ? "стоп в безубытке" : "стоп");
      else if(lastReason == DEAL_REASON_SO) why = "стоп-аут";
      else if(lastReason == DEAL_REASON_TP) why = "тейк";
      else if(lastReason == DEAL_REASON_CLIENT || lastReason == DEAL_REASON_MOBILE || lastReason == DEAL_REASON_WEB) why = "закрыто вручную";
      else why = "другое";
     }
   double R = (grp.planRisk > 0) ? pnl / grp.planRisk : 0;
   double bal = AccountInfoDouble(ACCOUNT_BALANCE);
   string dir = grp.buy ? "покупка" : "продажа";
   PrintFormat("ФИГУРА ЗАКРЫТА: %s %s, уровни %s, объём %.2f, прибыль %.2f $ (%.2fR), баланс %.2f, причина: %s",
               _Symbol, dir, grpLevels, grp.initVol, pnl, R, bal, why);
   string line = TimeToString(grp.opened, TIME_DATE | TIME_MINUTES) + ";" + TimeToString(tClose, TIME_DATE | TIME_MINUTES) + ";" +
                 _Symbol + ";" + dir + ";" + grpLevels + ";" + Num(grp.initVol, VolDigits()) + ";" + Num(pnl, 2) + ";" +
                 Num(R, 2) + ";" + Num(bal, 2) + ";" + why;
   WriteCsv(line);
   curMonthLine = MonthLine(curYM, "Этот месяц");
  }

// итоги месяца ym (год*12 + месяц-1) по файлу отчёта
string MonthLine(int ym, string title)
  {
   int y = ym / 12, m = ym % 12 + 1;
   int trades = 0, wins = 0;
   double sum = 0, startBal = 0;
   int h = FileOpen(CsvName(), FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON | FILE_SHARE_READ | FILE_SHARE_WRITE, '\t', CP_UTF8);
   if(h != INVALID_HANDLE)
     {
      int ln = 0;
      ushort sep = StringGetCharacter(";", 0);
      while(!FileIsEnding(h))
        {
         string s = FileReadString(h);
         ln++;
         if(ln == 1) continue;                                            // заголовок
         string p[];
         if(StringSplit(s, sep, p) < 10) continue;
         datetime tc = StringToTime(p[1]);
         if(tc <= 0) continue;
         MqlDateTime d; TimeToStruct(tc, d);
         if(d.year != y || d.mon != m) continue;
         double pnl = ParseNum(p[6]), bal = ParseNum(p[8]);
         if(trades == 0) startBal = bal - pnl;
         trades++;
         if(pnl > 0) wins++;
         sum += pnl;
        }
      FileClose(h);
     }
   if(trades == 0) return(StringFormat("%s (%02d.%d): закрытых сделок нет", title, m, y));
   return(StringFormat("%s (%02d.%d): сделок %d, прибыль %.2f $ (%+.1f%%), прибыльных %d из %d (%.0f%%)",
                       title, m, y, trades, sum, startBal > 0 ? sum / startBal * 100 : 0.0, wins, trades, 100.0 * wins / trades));
  }

int CurYM() { MqlDateTime d; TimeToStruct(TimeCurrent(), d); return(d.year * 12 + d.mon - 1); }

void InitMonth()
  {
   curYM = CurYM();
   curMonthLine  = MonthLine(curYM, "Этот месяц");
   prevMonthLine = MonthLine(curYM - 1, "Прошлый месяц");
   Print(prevMonthLine);
   Print(curMonthLine);
  }

void CheckMonth()
  {
   int ym = CurYM();
   if(curYM == 0) { InitMonth(); return; }
   if(ym == curYM) return;
   prevMonthLine = MonthLine(curYM, "Прошлый месяц");
   Print("===== ИТОГ МЕСЯЦА ===== ", prevMonthLine);
   curYM = ym;
   curMonthLine = MonthLine(curYM, "Этот месяц");
  }

string StatusLine()
  {
   if(grp.on)
     {
      double vol = 0, avg = AvgOpen(vol);
      return(StringFormat("Позиция: %s %.2f лота, средняя %s, стоп %s%s", grp.buy ? "ПОКУПКА" : "ПРОДАЖА", vol,
                          DoubleToString(avg, _Digits), DoubleToString(grp.slWant, _Digits),
                          grp.sid >= 0 ? ", фигура #" + IntegerToString(grp.sid) : ""));
     }
   int s = FindSetup(actSid);
   if(s >= 0 && st[s].alive)
     {
      string l = "";
      for(int k = 0; k < 5; k++) if(st[s].tk[k] != 0) l += LN[k] + " ";
      return(StringFormat("Лимитки фигуры #%d (%s): %s", st[s].id, st[s].buy ? "покупка" : "продажа",
                          l == "" ? (newsNow ? "сняты на время новостей" : "нет") : l));
     }
   return("Позиции нет, ждём новую фигуру");
  }

void UpdateComment()
  {
   string s = banner + "\nТолько для ТЕСТЕРА и ДЕМО-счёта";
   if(newsWarn != "") s += "\n" + newsWarn;
   s += "\n" + StatusLine();
   if(curMonthLine != "")  s += "\n" + curMonthLine;
   if(prevMonthLine != "") s += "\n" + prevMonthLine;
   Comment(s);
  }

//+------------------------------------------------------------------+
//| Новости: файл Common\Files\b1_news_utc.csv, строки               |
//| "YYYY.MM.DD HH:MM,USD" (время UTC, по возрастанию времени)       |
//+------------------------------------------------------------------+
bool LoadNews()
  {
   int h = FileOpen(NewsFile, FILE_READ | FILE_CSV | FILE_ANSI | FILE_COMMON, ',');
   if(h == INVALID_HANDLE) return(false);
   while(!FileIsEnding(h))
     {
      string t = FileReadString(h); if(FileIsEnding(h) && t == "") break;
      string c = FileReadString(h);
      datetime dt = StringToTime(t);
      if(dt == 0) continue;
      ArrayResize(newsT, nnews + 1, 20000); ArrayResize(newsC, nnews + 1, 20000);
      newsT[nnews] = dt; newsC[nnews] = c; nnews++;
     }
   FileClose(h);
   Print("Новостей загружено: ", nnews);
   return(nnews > 0);
  }

string Cur1() { return StringSubstr(_Symbol, 0, 3); }
string Cur2() { return StringSubstr(_Symbol, 3, 3); }

bool IsFx(string c)
  {
   return(c == "EUR" || c == "USD" || c == "GBP" || c == "JPY" || c == "AUD" || c == "CHF" || c == "CAD" || c == "NZD");
  }

// время идёт только вперёд — указатель newsPtr не возвращается назад
bool NewsBlocked(datetime serverTime)
  {
   if(nnews == 0) return(false);
   datetime u = ServerToUTC(serverTime);
   string c1 = Cur1(), c2 = Cur2();
   bool fx = IsFx(c1) && IsFx(c2);
   int w = NewsWindowMin * 60;
   while(newsPtr < nnews && newsT[newsPtr] < u - w) newsPtr++;
   for(int k = newsPtr; k < nnews; k++)
     {
      if(newsT[k] > u + w) break;
      if(fx ? (newsC[k] == c1 || newsC[k] == c2) : newsC[k] == "USD") return(true);
     }
   return(false);
  }

// раз в минуту: идёт ли сейчас окно новостей
void UpdateNews()
  {
   if(!UseNewsFilter || !newsOK) { newsNow = false; return; }
   long mnt = (long)TimeCurrent() / 60;
   if(mnt == newsMinute) return;
   newsMinute = mnt;
   bool b = NewsBlocked(TimeCurrent());
   if(b && !newsNow) PrintFormat("Новости: окно ±%d мин — лимитки снимаются", NewsWindowMin);
   if(!b && newsNow) Print("Новости: окно закончилось — лимитки выставляются снова");
   if(b != newsNow) { newsNow = b; UpdateComment(); }
  }

datetime ServerToUTC(datetime t)
  {
   if(ServerTimeMode == 1) return(t - ServerGMTOffset * 3600);
   MqlDateTime d; TimeToStruct(t, d);
   datetime dstStart = NthSunday(d.year, 3, 2) + 2 * 3600 + 7 * 3600;
   datetime dstEnd   = NthSunday(d.year, 11, 1) + 2 * 3600 + 7 * 3600;
   int off = (t >= dstStart && t < dstEnd) ? 3 : 2;
   return(t - off * 3600);
  }

datetime NthSunday(int y, int mon, int n)
  {
   MqlDateTime d; d.year = y; d.mon = mon; d.day = 1; d.hour = 0; d.min = 0; d.sec = 0;
   datetime t = StructToTime(d);
   TimeToStruct(t, d);
   int add = (7 - d.day_of_week) % 7;
   return(t + (add + 7 * (n - 1)) * 86400);
  }

//+------------------------------------------------------------------+
//| Рисунок: фигура с входом — A, B, пять уровней, стоп, цель         |
//+------------------------------------------------------------------+
void DrawSetup(int s)
  {
   string p = "B1_" + IntegerToString(objN++) + "_";
   datetime tA = H[st[s].aIdx].time, tB = H[st[s].bIdx].time, tEnd = TimeCurrent() + 48 * 3600;
   ObjectCreate(0, p + "AB", OBJ_TREND, 0, tA, st[s].A, tB, st[s].B);
   ObjectSetInteger(0, p + "AB", OBJPROP_COLOR, clrRoyalBlue); ObjectSetInteger(0, p + "AB", OBJPROP_WIDTH, 2);
   ObjectSetInteger(0, p + "AB", OBJPROP_RAY_RIGHT, false);
   Label(p + "tA", tA, st[s].A, "A", clrRoyalBlue);
   Label(p + "tB", tB, st[s].B, "B", clrRoyalBlue);
   for(int q = 0; q < 5; q++)
     {
      HLine(p + "lv" + IntegerToString(q), tB, st[s].lv[q], tEnd, clrOrange, STYLE_DOT);
      Label(p + "ln" + IntegerToString(q), tEnd, st[s].lv[q], LN[q], clrOrange);
     }
   HLine(p + "SL", tB, st[s].stop, tEnd, clrRed, STYLE_SOLID);
   HLine(p + "TP", tB, st[s].target1, tEnd, clrGreen, STYLE_SOLID);
  }

// отклонённая фигура: серая линия A→B и причина у точки A
void DrawReject(int aIdx, double a, int bIdx, double b, int why)
  {
   string p = "B1x_" + IntegerToString(objN++) + "_";
   ObjectCreate(0, p + "AB", OBJ_TREND, 0, H[aIdx].time, a, H[bIdx].time, b);
   ObjectSetInteger(0, p + "AB", OBJPROP_COLOR, clrSilver);
   ObjectSetInteger(0, p + "AB", OBJPROP_STYLE, STYLE_DOT);
   ObjectSetInteger(0, p + "AB", OBJPROP_RAY_RIGHT, false);
   Label(p + "why", H[aIdx].time, a, statShort[why], clrSilver);
  }

void Label(string nm, datetime t, double pr, string txt, color c)
  {
   ObjectCreate(0, nm, OBJ_TEXT, 0, t, pr);
   ObjectSetString(0, nm, OBJPROP_TEXT, txt);
   ObjectSetInteger(0, nm, OBJPROP_COLOR, c);
   ObjectSetInteger(0, nm, OBJPROP_FONTSIZE, 8);
  }

void HLine(string nm, datetime t1, double pr, datetime t2, color c, ENUM_LINE_STYLE s)
  {
   ObjectCreate(0, nm, OBJ_TREND, 0, t1, pr, t2, pr);
   ObjectSetInteger(0, nm, OBJPROP_COLOR, c);
   ObjectSetInteger(0, nm, OBJPROP_STYLE, s);
   ObjectSetInteger(0, nm, OBJPROP_RAY_RIGHT, false);
  }
//+------------------------------------------------------------------+
