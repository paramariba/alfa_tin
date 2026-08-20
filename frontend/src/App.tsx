import { useCallback, useEffect, useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import {
  ArrowDown, ArrowLeft, ArrowUp, Award, Banknote, BarChart3, BookOpen, Check, ChevronRight, Copy,
  CircleUserRound, ExternalLink, Flame, Gift, Heart, Home, Info, LineChart, LockKeyhole,
  LogOut, Moon, Newspaper, PiggyBank, RefreshCw, Search, Settings2, ShieldCheck, ShoppingBag, Sparkles, Sun,
  MessageCircle, PieChart, Send, Star, Target, Trash2, Trophy, UserCheck, UserPlus, UsersRound, Wallet, X, Zap
} from 'lucide-react'
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis } from 'recharts'
import { FALLBACK_LESSON, LESSON_CONTENT } from './lessonContent'
import {
  applyHostTheme, clearAccessToken, configureRuntime, emitPluginEvent, getAccessToken, getApiUrl,
  getMarketWebSocketUrl, isEmbedded, isTrustedHostMessage, rememberHostOrigin, setAccessToken,
} from './integration'

type Page = 'home' | 'market' | 'tin' | 'learn' | 'social' | 'profile'
type Sheet = null | 'portfolio' | 'convert' | 'shop' | 'contest' | 'referral' | 'instrument' | 'piggy' | 'streak' | 'lesson' | 'edit_profile' | 'security' | 'news' | 'monthly_report' | 'achievements' | 'social_profile' | 'share_trade'
type Instrument = { id:number; ticker:string; name:string; type:string; sector:string; risk_level:string; description:string; display_price_tkn:number; real_price_rub:number; change_pct:number; source:string; source_timestamp:string; position?:any; candles?:{t:string|number;v:number}[] }
type StreakState = {
  streak_count:number; claimed_today:boolean; can_claim:boolean; today:string; last_claimed_date:string|null
  current_reward:{xp:number;boost:number}; next_claim_at:string; seconds_until_next_claim:number; timezone:string
  week:{label:string;date:string;status:'claimed'|'available'|'missed'|'future'}[]
  history:{date:string;streak_day:number;xp:number;boost:number;claimed_at:string}[]
  total_rewards:{xp:number;boost:number;days:number}
}

async function api<T=any>(path:string, options?:RequestInit):Promise<T> {
  const token=getAccessToken()
  const response = await fetch(getApiUrl(path), { ...options, headers:{'Content-Type':'application/json', ...(token?{Authorization:`Bearer ${token}`}:{ }), ...(options?.headers||{})} })
  if (!response.ok) {
    const body = await response.json().catch(()=>({detail:'Что-то пошло не так'}))
    const message = Array.isArray(body.detail) ? body.detail.map((item:any)=>item.msg).join(', ') : body.detail
    if(response.status===401&&!path.startsWith('/auth/'))window.dispatchEvent(new Event('alfa-auth-expired'))
    if(response.status===403&&String(message).toLowerCase().includes('заблокирован')){
      localStorage.setItem('alfa-auth-notice',String(message))
      window.dispatchEvent(new Event('alfa-auth-expired'))
    }
    throw new Error(message || 'Ошибка запроса')
  }
  return response.json()
}
const fmt = (value:number|string, digits=0) => new Intl.NumberFormat('ru-RU',{maximumFractionDigits:digits,minimumFractionDigits:digits}).format(Number(value))
const ageFromDate=(value:string)=>{const born=new Date(`${value}T12:00:00`);if(Number.isNaN(born.getTime()))return null;const today=new Date();let age=today.getFullYear()-born.getFullYear();if(today.getMonth()<born.getMonth()||(today.getMonth()===born.getMonth()&&today.getDate()<born.getDate()))age--;return age}
const yearsWord=(age:number)=>age%10===1&&age%100!==11?'год':age%10>=2&&age%10<=4&&(age%100<12||age%100>14)?'года':'лет'

function AlfaMark(){return <div className="alfa-mark" aria-label="Альфа Тин"><b aria-hidden="true">А</b><span><strong>Альфа</strong><small>Тин</small></span></div>}

function AuthScreen({onAuthenticated}:{onAuthenticated:(token:string)=>void}){
  const [mode,setMode]=useState<'login'|'register'>('register')
  const [name,setName]=useState('')
  const [password,setPassword]=useState('')
  const [confirm,setConfirm]=useState('')
  const [error,setError]=useState(()=>{const notice=localStorage.getItem('alfa-auth-notice')||'';localStorage.removeItem('alfa-auth-notice');return notice})
  const [busy,setBusy]=useState(false)
  const submit=async(event:React.FormEvent)=>{
    event.preventDefault()
    setError('')
    if(mode==='register'&&password!==confirm){setError('Пароли не совпадают');return}
    setBusy(true)
    try{
      const result=await api<any>(`/auth/${mode}`,{method:'POST',body:JSON.stringify({name,password})})
      onAuthenticated(result.access_token)
    }catch(e:any){setError(e.message)}finally{setBusy(false)}
  }
  const changeMode=(next:'login'|'register')=>{setMode(next);setError('');setPassword('');setConfirm('')}
  return <main className="auth-page"><section className="auth-card"><header><AlfaMark/><span>Временный вход до подключения Alfa ID</span></header><div className="auth-mascot"><TinCharacter/><div><em>Привет!</em><strong>{mode==='register'?'Создадим твой профиль':'Рад снова тебя видеть'}</strong><p>Имя будет видно друзьям в Тин-Токе.</p></div></div><div className="auth-tabs"><button type="button" className={mode==='register'?'active':''} onClick={()=>changeMode('register')}>Регистрация</button><button type="button" className={mode==='login'?'active':''} onClick={()=>changeMode('login')}>Вход</button></div><form onSubmit={submit}><label><span>Имя</span><input autoFocus autoComplete="username" value={name} onChange={event=>setName(event.target.value)} placeholder="Например, Саша" minLength={2} maxLength={40} required/></label><label><span>Пароль</span><input type="password" autoComplete={mode==='register'?'new-password':'current-password'} value={password} onChange={event=>setPassword(event.target.value)} placeholder="Минимум 6 символов" minLength={mode==='register'?6:1} maxLength={72} required/></label>{mode==='register'&&<label><span>Повтори пароль</span><input type="password" autoComplete="new-password" value={confirm} onChange={event=>setConfirm(event.target.value)} placeholder="Ещё раз тот же пароль" minLength={6} maxLength={72} required/></label>}{error&&<p className="auth-error"><Info size={17}/>{error}</p>}<button className="auth-submit" disabled={busy}>{busy?'Подожди…':mode==='register'?'Создать профиль':'Войти'}</button></form><footer><ShieldCheck size={17}/><span>Это временная локальная авторизация. Позже её заменит Alfa ID.</span></footer></section></main>
}
function StatusDot({live=false}:{live?:boolean}){return <span className={`status ${live?'live':''}`}><i/>{live?'Live':'Демо-данные'}</span>}
function IconButton({label,children,onClick}:{label:string;children:any;onClick?:()=>void}){return <button className="icon-button" aria-label={label} onClick={onClick}>{children}</button>}
function ErrorBanner({text,onClose}:{text:string;onClose:()=>void}){return <motion.div className="error-banner" initial={{y:-20,opacity:0}} animate={{y:0,opacity:1}}><Info size={18}/><span>{text}</span><button onClick={onClose}><X size={16}/></button></motion.div>}

function TinCharacter({mood=86,small=false,equippedItems=[]}:{mood?:number;small?:boolean;equippedItems?:number[]}){
  const hasPanama = equippedItems.includes(1)
  const hasCrown = equippedItems.includes(6)
  const hasGlasses = equippedItems.includes(2)
  const hasOutfit = equippedItems.includes(3)
  const hasRocket = equippedItems.includes(5)
  return <motion.div className={`tin-character mascot ${small?'small':''}`} animate={{y:[0,-5,0],rotate:[0,-1,1,0]}} transition={{duration:4,repeat:Infinity,ease:'easeInOut'}} role="img" aria-label={`Тин, настроение ${mood}`}>
    {hasOutfit?<img className="mascot-frame outfit-render" src="/assets/tin-mascot-hoodie.png" alt="" draggable={false}/>:<><img className="mascot-frame frame-center" src="/assets/tin-mascot-look-center.png" alt="" draggable={false}/><img className="mascot-frame frame-right" src="/assets/tin-mascot-look-right.png" alt="" draggable={false}/><img className="mascot-frame frame-left" src="/assets/tin-mascot-look-left.png" alt="" draggable={false}/></>}
    {hasPanama && <span className="tin-headwear panama" aria-hidden="true"/>}
    {hasCrown && <span className="tin-headwear crown" aria-hidden="true">♛</span>}
    {hasGlasses && <span className="tin-glasses" aria-hidden="true"><i/><i/></span>}
    {hasRocket && <span className="tin-reaction" aria-hidden="true">🚀</span>}
  </motion.div>
}

type Theme = 'light'|'dark'
const readTheme=():Theme=>document.documentElement.dataset.theme==='dark'?'dark':'light'
function ThemeToggle(){
  const [theme,setTheme]=useState<Theme>(readTheme)
  const toggle=()=>{
    const next:Theme=theme==='light'?'dark':'light'
    document.documentElement.dataset.theme=next
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content',next==='dark'?'#0f0f11':'#f5f5f6')
    localStorage.setItem('alfa-tin-theme',next)
    setTheme(next)
  }
  return <button className="theme-toggle" onClick={toggle} aria-label={theme==='light'?'Включить тёмную тему':'Включить светлую тему'} title={theme==='light'?'Тёмная тема':'Светлая тема'}>{theme==='light'?<Moon size={18}/>:<Sun size={18}/>}</button>
}

function Nav({page,setPage,socialLabel='Тин-Ток'}:{page:Page;setPage:(p:Page)=>void;socialLabel?:string}){
  const items:[Page,string,any][]=[['home','Главная',Home],['market','Рынок',LineChart],['tin','Тин',Heart],['learn','Учёба',BookOpen],['social',socialLabel,UsersRound],['profile','Профиль',CircleUserRound]]
  const navigate=(next:Page)=>{setPage(next);requestAnimationFrame(()=>{window.scrollTo({top:0});document.querySelector('.phone-shell')?.scrollTo({top:0})})}
  return <nav className="bottom-nav" aria-label="Основная навигация">{items.map(([key,label,Icon])=><button key={key} className={page===key?'active':''} onClick={()=>navigate(key)}><span>{key==='tin'?<span className="tin-nav-face"><img src="/assets/tin-mascot.png" alt=""/></span>:<Icon size={23}/>}</span><em>{label}</em></button>)}</nav>
}

function AppHeader({title,sub,streakState,onStreakClick}:{title:string;sub?:string;streakState?:Partial<StreakState>;onStreakClick?:()=>void}){
  const count=streakState?.streak_count??0
  const status=streakState?.claimed_today?'claimed':'available'
  return <header className="app-header"><div><AlfaMark/><p>{sub}</p><h1>{title}</h1></div><div className="header-actions"><ThemeToggle/><button className={`streak ${status}`} onClick={onStreakClick} aria-label={`Серия: ${count} дней. ${streakState?.claimed_today?'Бонус получен':'Бонус доступен'}`}><Flame size={19} fill="currentColor"/><b>{count}</b><i aria-hidden="true"/></button></div></header>
}

function Goal({goal,coins,onOpen}:{goal:any;coins:number;onOpen:()=>void}){
  if(!goal)return null; const pct=Math.min(100,(coins/goal.price_ac)*100)
  return <button className="goal-block" onClick={onOpen}><div className="section-kicker"><Target size={17}/><span>Твоя цель</span><ChevronRight size={18}/></div><div className="goal-row"><div><h3>{goal.image_emoji} {goal.name}</h3><p>{fmt(coins)} из {fmt(goal.price_ac)} AC</p></div><strong>{Math.round(pct)}%</strong></div><div className="progress"><motion.i initial={{width:0}} animate={{width:`${pct}%`}} transition={{duration:.8,ease:'easeOut'}}/></div><small>Осталось {fmt(Math.max(0,goal.price_ac-coins))} AC</small></button>
}

function HomeNewsWidget({onOpen}:{onOpen:()=>void}){
  const [items,setItems]=useState<any[]>([])
  useEffect(()=>{api<any>('/news/portfolio-insights').then(result=>setItems((result.items||[]).slice(0,4))).catch(()=>{})},[])
  return <section className="home-news-widget"><header><div><span>КОМПАНИИ В ПОРТФЕЛЕ</span><strong>Что произошло</strong></div><button onClick={onOpen}>Все новости <ChevronRight size={16}/></button></header>{items.length?<div>{items.map(item=><button key={item.instrument.id} onClick={onOpen}><b>{item.instrument.ticker}</b><span>{item.insight.headline}</span><ChevronRight size={15}/></button>)}</div>:<button className="home-news-empty" onClick={onOpen}><Newspaper size={20}/><span>Купи первую акцию — здесь появятся новости компании</span><ChevronRight size={16}/></button>}</section>
}

function HomePage({dashboard,open,setPage,startMarketMission,missionDone,openQuests}:{dashboard:any;open:(s:Sheet)=>void;setPage:(p:Page)=>void;startMarketMission:()=>void;missionDone:boolean;openQuests:()=>void}){
  const coins=Number(dashboard.wallet?.alfa_coins||0)
  const breakdown=dashboard.wallet_breakdown||{}
  const questTotal=Number(dashboard.quest_summary?.total||0)
  const questsDone=Math.min(questTotal,Number(dashboard.quest_summary?.done||0))
  return <motion.main className="page home-page" initial={{opacity:0}} animate={{opacity:1}}>
    <AppHeader title={`Привет, ${dashboard.user?.display_name||'Саша'}`} streakState={dashboard.streak_state} onStreakClick={()=>open('streak')}/>
    <button className="balance-plane wallet-card" onClick={()=>open('portfolio')}>
      <header className="wallet-card-header"><span><Wallet size={15}/>Основной счёт</span></header>
      <div className="card-balance"><span>МОЖНО ПОТРАТИТЬ</span><motion.strong initial={{opacity:0,y:8}} animate={{opacity:1,y:0}}>{fmt(breakdown.spendable??dashboard.wallet?.token_cash??0,2)} <small>TKN</small></motion.strong><em>Всего в кошельке {fmt(dashboard.net_worth,2)} TKN</em></div>
      <img className="wallet-tin-3d" src="/assets/tin-wallet-3d-v2.png" alt="" aria-hidden="true"/>
      <div className="wallet-assets" aria-label="Состав кошелька">
        <span><small>Акции</small><b>{fmt(breakdown.stocks||0,0)} TKN</b></span>
        <span><small>Фонды</small><b>{fmt(breakdown.funds||0,0)} TKN</b></span>
        <span><small>Копилка</small><b>{fmt(breakdown.piggy||0,0)} TKN</b></span>
      </div>
      <footer><span>Открыть весь кошелёк</span><div><b className="wallet-ac-badge">{fmt(coins)} <small>AC</small></b><ChevronRight size={19}/></div></footer>
    </button>
    <section className="quick-actions" aria-label="Быстрые действия">
      <button onClick={()=>open('convert')}><i className="red"><ArrowDown size={22}/></i><span>Получить AC</span></button>
      <button onClick={()=>setPage('market')}><i><LineChart size={22}/></i><span>Инвестировать</span></button>
      <button onClick={()=>open('shop')}><i><ShoppingBag size={22}/></i><span>Магазин</span></button>
    </section>
    <Goal goal={dashboard.goal} coins={coins} onOpen={()=>open('shop')}/>
    <HomeNewsWidget onOpen={()=>open('news')}/>
    <button className={`tin-prompt ${missionDone?'complete':''}`} onClick={missionDone?()=>setPage('market'):startMarketMission}><TinCharacter small/><div><span>{missionDone?'Задание выполнено':'Практика с Тином'}</span><strong>{missionDone?'Ты нашёл лидера по движению':'Найди самую подвижную акцию сегодня'}</strong><em>{missionDone?'Посмотреть рынок':<>Разберёшься, что такое волатильность <ChevronRight size={16}/></>}</em></div></button>
    <section className="quest-line"><div><span>Текущие задания</span><b>{questsDone}/{questTotal}</b></div><div className="segments" aria-label={`Выполнено ${questsDone} из ${questTotal}`}>{Array.from({length:questTotal},(_,index)=><i key={index} className={index<questsDone?'done':''}/>)}</div><footer><small>{dashboard.quest_summary?.daily_total||0} на сегодня · {dashboard.quest_summary?.weekly_total||0} на неделю</small><button onClick={openQuests}>{questTotal>0&&questsDone>=questTotal?'Посмотреть':'Продолжить'} <ChevronRight size={16}/></button></footer></section>
    <button className="contest-entry" onClick={()=>open('contest')}><div><span>CONTEST</span><strong>Проверь стратегию против других</strong><p>Отдельный кошелёк, 1 000 CT и никакого риска</p></div><Trophy size={48}/></button>
  </motion.main>
}

function MarketPage({instruments,select,openPiggy,streakState,onStreakClick,missionTargetId}:{instruments:Instrument[];select:(i:Instrument)=>void;openPiggy:()=>void;streakState?:StreakState;onStreakClick:()=>void;missionTargetId:number|null}){
  const [tab,setTab]=useState<'stock'|'fund'|'piggy'>('stock'); const [search,setSearch]=useState('')
  const filtered=instruments.filter(i=>i.type===tab && `${i.ticker} ${i.name}`.toLowerCase().includes(search.toLowerCase()))
  const list=missionTargetId!==null&&tab==='stock'?[...filtered].sort((a,b)=>a.id===missionTargetId?-1:b.id===missionTargetId?1:Math.abs(b.change_pct)-Math.abs(a.change_pct)):filtered
  return <motion.main className="page market-page" initial={{opacity:0,y:8}} animate={{opacity:1,y:0}}>
    <AppHeader title="Рынок" sub="Московская биржа" streakState={streakState} onStreakClick={onStreakClick}/>
    {missionTargetId!==null&&<section className="market-mission"><TinCharacter small/><div><span>Задание Тина</span><strong>Найди самое большое движение</strong><p>Сравни проценты по модулю: −4% сильнее, чем +2%. Я отсортировал акции, осталось выбрать первую.</p><small>Результат пойдёт в задание «Изучи одну компанию»</small></div></section>}
    <div className="tabs"><button className={tab==='stock'?'active':''} onClick={()=>setTab('stock')}>Акции</button><button className={tab==='fund'?'active':''} onClick={()=>setTab('fund')}>Фонды</button><button className={tab==='piggy'?'active':''} onClick={()=>{setTab('piggy');openPiggy()}}>Копилка</button></div>
    <label className="search"><Search size={20}/><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Компания или тикер"/></label>
    <div className="market-summary"><div><span>Рынок сегодня</span><strong>{instruments.filter(i=>i.change_pct>0).length} растут</strong></div><StatusDot live={instruments.some(i=>i.source==='finam')}/></div>
    <section className="instrument-list">{list.map((item,index)=><motion.button key={item.id} onClick={()=>select(item)} initial={{opacity:0,x:-8}} animate={{opacity:1,x:0}} transition={{delay:index*.025}}><div className={`ticker-logo c${item.id%5}`}>{item.ticker.slice(0,2)}</div><div className="instrument-name"><strong>{item.ticker}</strong><span>{item.name}</span></div><div className="instrument-price"><strong>{fmt(item.display_price_tkn,2)} TKN</strong><span className={item.change_pct>=0?'positive':'negative'}>{item.change_pct>=0?'+':''}{fmt(item.change_pct,2)}%</span></div><ChevronRight size={17}/></motion.button>)}</section>
    <p className="market-note"><Info size={16}/> Цена в игре равна котировке в рублях ÷ 100. Результат позиции ускорен ×10.</p>
  </motion.main>
}

function TinPage({pet,coins=0,refresh,notify,streakState,onStreakClick}:{pet:any;coins?:number;refresh:()=>void;notify:(s:string)=>void;streakState?:StreakState;onStreakClick:()=>void}){
  type TinAction = 'pet'|'talk'|'task'
  const [cd,setCd]=useState<Record<string,number>>({pet:0,talk:0,task:0})
  const [reaction,setReaction]=useState<{kind:TinAction;id:number}|null>(null)

  useEffect(()=>{
    if(!pet?.cooldowns)return
    setCd({
      pet:Math.max(0,Number(pet.cooldowns.pet)||0),
      talk:Math.max(0,Number(pet.cooldowns.talk)||0),
      task:Math.max(0,Number(pet.cooldowns.task)||0),
    })
  },[pet?.cooldowns?.pet,pet?.cooldowns?.talk,pet?.cooldowns?.task])

  useEffect(()=>{
    const interval=setInterval(()=>{
      setCd(prev=>{
        let updated=false
        const next={...prev}
        for(const k in next){
          if(next[k]>0){next[k]-=1; updated=true}
        }
        return updated?next:prev
      })
    },1000)
    return ()=>clearInterval(interval)
  },[])

  useEffect(()=>{
    if(!reaction)return
    const timer=window.setTimeout(()=>setReaction(null),2200)
    return()=>window.clearTimeout(timer)
  },[reaction])

  const interact=async(action:TinAction)=>{
    if(cd[action]>0){
      notify(`Подожди ${cd[action]} сек. перед повторным действием`)
      return
    }
    try{
      const r=await api<any>('/tamagotchi/interact',{method:'POST',body:JSON.stringify({action})})
      setReaction({kind:action,id:Date.now()})
      notify(r.message)
      if(r.pet?.cooldowns)setCd(r.pet.cooldowns)
      await refresh()
    }catch(e:any){notify(e.message)}
  }

  const buy=async(id:number)=>{
    try{
      await api(`/tamagotchi/shop/${id}/buy`,{method:'POST'})
      notify('Куплено и сразу применено!')
      await refresh()
    }catch(e:any){notify(e.message)}
  }

  const equip=async(id:number)=>{
    try{
      const result=await api<any>(`/tamagotchi/equip/${id}`,{method:'POST'})
      notify(result.equipped?'Стиль обновлён!':'Предмет снят')
      await refresh()
    }catch(e:any){notify(e.message)}
  }

  const equippedItems:number[] = useMemo(()=>{
    try{ return JSON.parse(pet?.equipped_items_json||'[]') }catch{ return [] }
  },[pet?.equipped_items_json])
  const traderRoom = equippedItems.includes(4)
  const slotNames:Record<string,string>={head:'Головной убор',eyes:'Очки',outfit:'Одежда',room:'Фон комнаты',mood:'Реакция'}
  const reactionKind=reaction?.kind
  const reactionCopy=reactionKind==='pet'?'М-м-м… Спасибо!':reactionKind==='talk'?'Слушаю тебя!':reactionKind==='task'?'Берусь за дело!':traderRoom?'Терминал готов. Смотрим на факты, а не на шум.':'Сегодня без спешки: сначала изучим, потом решим.'
  const reactionMotion=reactionKind==='pet'?{scale:[1,1.08,.98,1],rotate:[0,-4,4,0]}:reactionKind==='talk'?{scale:[1,1.04,1],x:[0,-7,7,0],rotate:[0,-2,2,0]}:reactionKind==='task'?{scale:[1,.96,1.07,1],y:[0,7,-10,0]}:{scale:1,x:0,y:0,rotate:0}

  return <motion.main className="page tin-page" initial={{opacity:0}} animate={{opacity:1}}>
    <AppHeader title="Комната Тина" sub="Твой инвест-помощник" streakState={streakState} onStreakClick={onStreakClick}/>
    <section className={`tin-room ${traderRoom?'trader-room':''}`}>
      {traderRoom&&<div className="trade-terminal" aria-hidden="true"><span><i/><i/><i/><i/></span><b>LIVE</b></div>}
      <motion.div className={`tin-response-stage ${reactionKind||'idle'}`} animate={reactionMotion} transition={{duration:reactionKind==='talk'?.7:.85,ease:'easeOut'}}>
        <TinCharacter mood={pet?.mood} equippedItems={equippedItems}/>
        <AnimatePresence>{reaction&&<motion.div className="tin-reaction-pop" initial={{opacity:0,scale:.55,y:15}} animate={{opacity:1,scale:1,y:0}} exit={{opacity:0,scale:.7,y:-18}} transition={{duration:.25}}>{reactionKind==='pet'?<Heart size={18} fill="currentColor"/>:reactionKind==='talk'?<MessageCircle size={18} fill="currentColor"/>:<Check size={19}/>}<b>{reactionKind==='pet'?'+ дружба':reactionKind==='talk'?'+ настроение':'готово'}</b></motion.div>}</AnimatePresence>
      </motion.div>
      <motion.div className={`speech ${reactionKind?'active':''}`} animate={{opacity:1,y:0}} aria-live="polite">{reactionCopy}</motion.div>
    </section>
    <section className="pet-stats">{[['Настроение',pet?.mood||0],['Энергия',pet?.energy||0],['Знания',pet?.knowledge||0],['Дружба',pet?.friendship||0]].map(([label,value])=><div key={String(label)}><span>{label}</span><i><b style={{width:`${value}%`}}/></i><em>{value}</em></div>)}</section>
    <div className="pet-actions">
      <button className={`${cd.pet>0?'cd ':''}${reactionKind==='pet'?'reacting':''}`} onClick={()=>interact('pet')}><Heart size={19}/>{cd.pet>0?`Гладить (${cd.pet}s)`:'Погладить'}</button>
      <button className={`${cd.talk>0?'cd ':''}${reactionKind==='talk'?'reacting':''}`} onClick={()=>interact('talk')}><Sparkles size={19}/>{cd.talk>0?`Поговорить (${cd.talk}s)`:'Поговорить'}</button>
      <button className={`${cd.task>0?'cd ':''}${reactionKind==='task'?'reacting':''}`} onClick={()=>interact('task')}><Zap size={19}/>{cd.task>0?`Задание (${cd.task}s)`:'Задание'}</button>
    </div>
    <section className="wardrobe">
      <div className="section-title"><div><span>Гардероб (Баланс: {fmt(coins)} AC)</span><h2>Новый образ для Тина</h2></div><ShoppingBag size={22}/></div>
      <div className="cosmetic-row">
        {pet?.items?.map((item:any)=>{
          const isOwned = Boolean(item.acquired_at)
          const isEquipped = equippedItems.includes(item.id)
          return (
            <button key={item.id} onClick={()=>{ if(isOwned){ equip(item.id) }else{ buy(item.id) } }} className={isEquipped?'equipped':isOwned?'owned':''}>
              <b>{item.emoji}</b>
              <small>{slotNames[item.slot]||item.slot}</small>
              <span>{item.name}</span>
              <em>{isEquipped?'Снять':isOwned?(item.slot==='room'?'Выбрать фон':item.slot==='mood'?'Включить':'Надеть'):`${item.price_ac} AC`}</em>
            </button>
          )
        })}
      </div>
    </section>
  </motion.main>
}

function LearnPage({lessons,quests,user,refresh,notify,streakState,onStreakClick,onSelectLesson,initialMode='path'}:{lessons:any[];quests:any[];user?:any;refresh:()=>void;notify:(s:string)=>void;streakState?:StreakState;onStreakClick:()=>void;onSelectLesson:(l:any)=>void;initialMode?:'path'|'quests'}){
  const [mode,setMode]=useState<'path'|'quests'>(initialMode)
  useEffect(()=>setMode(initialMode),[initialMode])
  const claim=async(id:number)=>{try{const r=await api<any>(`/quests/${id}/claim`,{method:'POST'});notify(`Награда: +${r.xp} XP`);refresh()}catch(e:any){notify(e.message)}}
  const level = user?.level || 2
  const xp = user?.xp || 820
  const nextXp = level * 500
  const levelTitle = level >= 5 ? 'Мастер' : level >= 3 ? 'Стратег' : 'Исследователь'

  return <motion.main className="page learn-page" initial={{opacity:0,y:8}} animate={{opacity:1,y:0}}><AppHeader title="Учёба" sub="Коротко и по делу" streakState={streakState} onStreakClick={onStreakClick}/>
    <div className="tabs"><button className={mode==='path'?'active':''} onClick={()=>setMode('path')}>Маршрут</button><button className={mode==='quests'?'active':''} onClick={()=>setMode('quests')}>Задания</button></div>
    {mode==='path'?<><section className="learn-hero"><div><span>Уровень {level}</span><strong>{levelTitle}</strong><p>{fmt(xp)} / {fmt(nextXp)} XP</p></div><Award size={54}/></section><section className="learning-path">{lessons.map((l,index)=><div key={l.id} className={l.completed_at?'complete':''}><button onClick={()=>onSelectLesson(l)}><span>{l.completed_at?<Check size={22}/>:index+1}</span></button><aside><em>{l.course}</em><strong>{l.title}</strong><p>{l.description}</p><small>+{l.xp_reward} XP · +{l.boost_reward} boost</small></aside></div>)}</section></>:<section className="quest-list">{quests.map(q=><button key={q.id} onClick={()=>q.progress>=q.target&&!q.claimed&&claim(q.id)}><span className="quest-icon">{q.type==='daily'?'⚡':'🏆'}</span><div><em>{q.type==='daily'?'Сегодня':'На неделе'}</em><strong>{q.title}</strong><p>{Math.min(q.progress,q.target)} / {q.target}</p></div><i className={q.claimed?'claimed':''}>{q.claimed?<Check/>:q.progress>=q.target?'Забрать':`+${q.boost_reward}`}</i></button>)}</section>}
  </motion.main>
}

function ProfilePage({dashboard,achievements,open,onStreakClick,onLogout}:{dashboard:any;achievements:any[];open:(s:Sheet)=>void;onStreakClick:()=>void;onLogout:()=>void}){
  const xp=Math.max(0,Number(dashboard.user?.xp??0))
  const level=Math.max(1,Number(dashboard.user?.level??1))
  const levelStart=(level-1)*500
  const nextLevelXp=level*500
  const levelProgress=Math.max(0,Math.min(100,(xp-levelStart)/500*100))
  const levelName=level>=5?'Мастер':level>=3?'Стратег':'Исследователь'
  return <motion.main className="page profile-page" initial={{opacity:0}} animate={{opacity:1}}><AppHeader title="Профиль" sub="Твой прогресс" streakState={dashboard.streak_state} onStreakClick={onStreakClick}/>
    <section className="profile-hero"><div className="avatar">{(dashboard.user?.display_name||'С')[0]}</div><div><strong>{dashboard.user?.display_name||'Саша'}</strong><span>{levelName} · уровень {level}</span></div><button className="profile-settings" aria-label="Редактировать профиль" onClick={()=>open('edit_profile')}><Settings2 size={22}/></button></section>
    <button className="profile-public-id" onClick={()=>navigator.clipboard?.writeText(dashboard.user?.public_id||dashboard.user?.referral_code||'')}><span>Твой ID для друзей</span><strong>{dashboard.user?.public_id||dashboard.user?.referral_code}</strong><Copy size={18}/></button>
    <section className="level-progress-card"><header><div><span>До уровня {level+1}</span><strong>{fmt(Math.max(0,nextLevelXp-xp))} XP</strong></div><b>{Math.round(levelProgress)}%</b></header><div className="level-progress-track"><i style={{width:`${levelProgress}%`}}/></div><footer><span>{fmt(xp)} XP</span><span>{fmt(nextLevelXp)} XP</span></footer></section>
    <section className="profile-stats"><div><strong>{fmt(xp)}</strong><span>всего XP</span></div><div><strong>{dashboard.streak_state?.streak_count??0}</strong><span>дней подряд</span></div><div><strong>{achievements.filter(item=>item.unlocked).length}/{achievements.length||5}</strong><span>достижений</span></div></section>
    <div className="menu-list"><button onClick={()=>open('monthly_report')}><BarChart3/><span><strong>Разбор месяца</strong><em>Где потерял TKN и что улучшить</em></span><ChevronRight/></button><button onClick={()=>open('achievements')}><Award/><span><strong>Достижения</strong><em>{achievements.filter(item=>item.unlocked).length} из {achievements.length||5} открыто</em></span><ChevronRight/></button><button onClick={()=>open('portfolio')}><Wallet/><span><strong>Портфель и история</strong><em>Позиции и сделки</em></span><ChevronRight/></button><button onClick={()=>open('shop')}><Gift/><span><strong>Магазин и цель</strong><em>{fmt(dashboard.wallet?.alfa_coins||0)} Alfa Coins</em></span><ChevronRight/></button><button onClick={()=>open('referral')}><Star/><span><strong>Пригласить друга</strong><em>До 100 TKN за приглашение</em></span><ChevronRight/></button><button onClick={()=>open('contest')}><Trophy/><span><strong>Contest</strong><em>Отдельный соревновательный режим</em></span><ChevronRight/></button><button onClick={()=>open('security')}><ShieldCheck/><span><strong>Безопасность</strong><em>Пароль, сессия и публичные данные</em></span><ChevronRight/></button><button className="logout-row" onClick={onLogout}><LogOut/><span><strong>Выйти</strong><em>Сменить пользователя на этом устройстве</em></span><ChevronRight/></button></div>
    <p className="legal">Котировки используются только для игровой симуляции. Не является индивидуальной инвестиционной рекомендацией.</p>
  </motion.main>
}

function SocialUserCard({user,onOpen,onToggle}:{user:any;onOpen:(id:number)=>void;onToggle:(id:number)=>void}){
  return <article className="social-user-card"><button className="social-user-main" onClick={()=>onOpen(user.id)}><span className={`social-avatar c${user.id%5}`}>{user.avatar}</span><div><em>{user.rank?`#${user.rank} по капиталу`:`Уровень ${user.level}`}</em><strong>{user.display_name}</strong><small>{user.public_id} · {fmt(user.capital_tkn,0)} TKN</small></div><ChevronRight size={17}/></button><button className={user.is_friend?'friend-toggle active':'friend-toggle'} aria-label={user.is_friend?'Удалить из друзей':'Добавить в друзья'} onClick={()=>onToggle(user.id)}>{user.is_friend?<UserCheck size={18}/>:<UserPlus size={18}/>}</button></article>
}

function PostText({text,mentions,onOpenInstrument}:{text:string;mentions:any[];onOpenInstrument:(id:number)=>void}){
  const byTicker=new Map((mentions||[]).map(item=>[String(item.ticker).toUpperCase(),item]))
  return <p className="post-text">{text.split(/(@[A-Za-z0-9]{1,12})/g).map((part,index)=>{const instrument=part.startsWith('@')?byTicker.get(part.slice(1).toUpperCase()):null;return instrument?<button key={`${part}-${index}`} onClick={()=>onOpenInstrument(instrument.id)}>{part}</button>:part})}</p>
}

function SocialPage({fallbackTitle,streakState,onStreakClick,onOpenUser,onOpenInstrument,version,notify}:{fallbackTitle:string;streakState?:StreakState;onStreakClick:()=>void;onOpenUser:(id:number)=>void;onOpenInstrument:(id:number)=>void;version:number;notify:(text:string)=>void}){
  const [scope,setScope]=useState<'top'|'friends'>('top')
  const [data,setData]=useState<any>(null)
  const [loading,setLoading]=useState(true)
  const [search,setSearch]=useState('')
  const [searchResults,setSearchResults]=useState<any[]>([])
  const [postText,setPostText]=useState('')
  const [posting,setPosting]=useState(false)
  const load=useCallback(async()=>{setLoading(true);try{setData(await api(`/social/feed?scope=${scope}`))}catch(e:any){notify(e.message)}finally{setLoading(false)}},[scope,notify])
  useEffect(()=>{load()},[load,version])
  useEffect(()=>{const term=search.trim();if(!term){setSearchResults([]);return}const timer=window.setTimeout(()=>api<any[]>(`/social/users?search=${encodeURIComponent(term)}`).then(setSearchResults).catch(()=>setSearchResults([])),220);return()=>window.clearTimeout(timer)},[search,version])
  const toggle=async(id:number)=>{try{const result=await api<any>(`/social/friends/${id}`,{method:'POST'});setSearchResults(current=>current.map(user=>user.id===id?{...user,is_friend:result.is_friend}:user));notify(result.message);await load()}catch(e:any){notify(e.message)}}
  const publish=async()=>{if(!postText.trim()||posting)return;setPosting(true);try{const result=await api<any>('/social/posts',{method:'POST',body:JSON.stringify({comment:postText.trim()})});setPostText('');notify(result.message);await load()}catch(e:any){notify(e.message)}finally{setPosting(false)}}
  const removePost=async(id:number)=>{if(!window.confirm('Удалить этот пост?'))return;try{const result=await api<any>(`/social/posts/${id}`,{method:'DELETE'});notify(result.message);await load()}catch(e:any){notify(e.message)}}
  const posts=data?.posts||[]
  return <motion.main className="page social-page" initial={{opacity:0,y:8}} animate={{opacity:1,y:0}}><AppHeader title={data?.title||fallbackTitle} sub="Посты о решениях сообщества" streakState={streakState} onStreakClick={onStreakClick}/>
    <section className="social-intro"><MessageCircle size={25}/><div><strong>Мнения без раскрытия сделок</strong><p>Упомяни инструмент через @тикер — пост прикрепит ссылку на него, а данные твоих транзакций останутся приватными.</p></div></section>
    <section className="social-composer"><textarea value={postText} maxLength={300} onChange={event=>setPostText(event.target.value)} placeholder="Что думаешь? Упомяни акцию: @YDEX или @TMOS"/><footer><span><b>@тикер</b> прикрепит ссылку на инструмент · {postText.length}/300</span><button disabled={posting||!postText.trim()} onClick={publish}><Send size={16}/>{posting?'Публикуем':'Опубликовать'}</button></footer></section>
    <div className="tabs social-tabs"><button className={scope==='top'?'active':''} onClick={()=>setScope('top')}>Топ по капиталу</button><button className={scope==='friends'?'active':''} onClick={()=>setScope('friends')}>Друзья · {data?.friends?.length||0}</button></div>
    <div className="social-search"><Search size={18}/><input value={search} onChange={event=>setSearch(event.target.value.toUpperCase())} placeholder="ID пользователя, например TIN-A1B2C3"/>{search&&<button onClick={()=>setSearch('')} aria-label="Очистить поиск"><X size={16}/></button>}</div>
    {search.trim()&&<section className="social-search-results"><div className="section-title"><div><span>ПОИСК</span><h2>{searchResults.length?`Найдено: ${searchResults.length}`:'Никого не нашли'}</h2></div></div>{searchResults.map((user:any)=><SocialUserCard key={user.id} user={user} onOpen={onOpenUser} onToggle={toggle}/>)}</section>}
    {scope==='top'&&<section className="social-ranking"><div className="section-title"><div><span>ЛИДЕРЫ</span><h2>Топ пользователей</h2></div></div>{data?.top_users?.map((user:any)=><SocialUserCard key={user.id} user={user} onOpen={onOpenUser} onToggle={toggle}/>)}</section>}
    {loading?<div className="social-loading"><RefreshCw/><span>Обновляем посты…</span></div>:posts.length===0?<div className="social-empty"><MessageCircle/><strong>В ленте пока тихо</strong><span>Добавь пользователя в друзья или напиши первый пост.</span></div>:<section className="social-feed"><div className="section-title"><div><span>{scope==='top'?'ИЗ СООБЩЕСТВА':'ОТ ДРУЗЕЙ'}</span><h2>Посты об инвестициях</h2></div></div>{posts.map((post:any)=><article className="social-post" key={post.id}><div className="post-heading"><button className="post-author" disabled={post.user_id===data?.viewer_id} onClick={()=>onOpenUser(post.user_id)}><span className={`social-avatar c${post.user_id%5}`}>{post.display_name[0]}</span><span><strong>{post.display_name}{post.user_id===data?.viewer_id?' · ты':''}</strong><small>{post.public_id} · {new Date(post.created_at).toLocaleDateString('ru-RU',{day:'numeric',month:'short'})}</small></span>{post.user_id!==data?.viewer_id&&<ChevronRight size={16}/>}</button>{post.user_id===data?.viewer_id&&<button className="post-delete" aria-label="Удалить пост" title="Удалить пост" onClick={()=>removePost(post.id)}><Trash2 size={16}/></button>}</div><PostText text={post.comment} mentions={post.mentions} onOpenInstrument={onOpenInstrument}/>{post.mentions?.length>0&&<div className="mentioned-instruments">{post.mentions.map((instrument:any)=><button key={instrument.id} onClick={()=>onOpenInstrument(instrument.id)}><b>@{instrument.ticker}</b><span>{instrument.name}</span><ChevronRight size={15}/></button>)}</div>}</article>)}</section>}
  </motion.main>
}

function SocialProfileSheet({userId,onClose,onChanged,done,onOpenInstrument}:{userId:number;onClose:()=>void;onChanged:()=>void;done:(text:string)=>void;onOpenInstrument:(id:number)=>void}){
  const [user,setUser]=useState<any>(null)
  const [busy,setBusy]=useState(false)
  const load=useCallback(()=>api(`/social/users/${userId}`).then(setUser).catch((e:any)=>done(e.message)),[userId,done])
  useEffect(()=>{load()},[load])
  const toggle=async()=>{setBusy(true);try{const result=await api<any>(`/social/friends/${userId}`,{method:'POST'});done(result.message);await load();onChanged()}catch(e:any){done(e.message)}finally{setBusy(false)}}
  return <SheetShell title={user?.display_name||'Профиль пользователя'} onClose={onClose} wide><div className="sheet-content public-profile">{!user?<div className="social-loading"><RefreshCw/><span>Загружаем профиль…</span></div>:<><section className="public-profile-hero"><span className={`social-avatar c${user.id%5}`}>{user.avatar}</span><div><strong>{user.display_name}</strong><em>{user.public_id} · уровень {user.level}</em></div><button className={user.is_friend?'active':''} disabled={busy} onClick={toggle}>{user.is_friend?<><UserCheck/>В друзьях</>:<><UserPlus/>Добавить</>}</button></section><section className="public-capital"><span>Игровой капитал</span><strong>{fmt(user.capital_tkn,2)} TKN</strong><small>Публичные данные симулятора</small></section><h3 className="sheet-title">Портфель</h3><div className="public-positions">{user.positions?.map((position:any)=><div key={position.instrument_id}><span><strong>{position.ticker}</strong><small>{position.name}</small></span><b>{fmt(position.value_tkn,2)} TKN</b></div>)}</div><h3 className="sheet-title">Опубликованные посты</h3><div className="profile-posts">{user.posts?.length?user.posts.map((post:any)=><article key={post.id}><PostText text={post.comment} mentions={post.mentions} onOpenInstrument={onOpenInstrument}/>{post.mentions?.length>0&&<div className="mentioned-instruments compact">{post.mentions.map((instrument:any)=><button key={instrument.id} onClick={()=>onOpenInstrument(instrument.id)}><b>@{instrument.ticker}</b><span>{instrument.name}</span><ChevronRight size={14}/></button>)}</div>}<small>{new Date(post.created_at).toLocaleDateString('ru-RU')}</small></article>):<p className="muted-copy">Пользователь ещё ничем не поделился.</p>}</div><p className="social-disclaimer"><ShieldCheck size={17}/>Упоминание инструмента — ссылка для контекста, а не рекомендация его покупать.</p></>}</div></SheetShell>
}

function AchievementsSheet({items,onClose,refresh,done}:{items:any[];onClose:()=>void;refresh:()=>void;done:(s:string)=>void}){
  const [busy,setBusy]=useState<number|null>(null)
  const claim=async(id:number)=>{setBusy(id);try{const result=await api<any>(`/achievements/${id}/claim`,{method:'POST'});done(result.message);await refresh()}catch(e:any){done(e.message)}finally{setBusy(null)}}
  return <SheetShell title="Достижения" onClose={onClose}><div className="sheet-content achievement-sheet"><p>Достижение открывается за реальное действие в симуляторе. Награду можно забрать только один раз.</p>{items.map(item=><article key={item.id} className={`${item.unlocked?'unlocked':'locked'} ${item.claimed?'claimed':''}`}><i>{item.icon}</i><div><strong>{item.title}</strong><span>{item.progress} из {item.target}</span><div className="progress"><b style={{width:`${Math.min(100,item.progress/item.target*100)}%`}}/></div></div><button disabled={!item.unlocked||item.claimed||busy===item.id} onClick={()=>claim(item.id)}>{item.claimed?<Check size={17}/>:item.unlocked?'Забрать':'Закрыто'}</button></article>)}</div></SheetShell>
}

function MonthlyReportSheet({onClose}:{onClose:()=>void}){
  const currentMonth=new Date().toLocaleDateString('sv-SE',{year:'numeric',month:'2-digit'}).slice(0,7)
  const [month,setMonth]=useState(currentMonth)
  const [data,setData]=useState<any>()
  const [loading,setLoading]=useState(true)
  const [error,setError]=useState('')
  const load=async(force=false)=>{setLoading(true);setError('');try{setData(await api(`/coach/monthly-report?month=${month}${force?'&refresh=true':''}`))}catch(e:any){setError(e.message)}finally{setLoading(false)}}
  useEffect(()=>{load()},[month])
  const actionLabel=(item:any)=>item.kind==='buy'?`Покупка ${item.ticker}`:item.kind==='sell'?`Продажа ${item.ticker}`:item.kind==='conversion'?'Обмен TKN на AC':item.kind==='lesson'?`Урок: ${item.title}`:item.kind==='piggy_deposit'?'Пополнение копилки':'Вывод из копилки'
  return <SheetShell title="Разбор месяца" onClose={onClose} wide><div className="sheet-content monthly-report"><div className="monthly-toolbar"><label>Месяц<input type="month" max={currentMonth} value={month} onChange={event=>setMonth(event.target.value)}/></label><button onClick={()=>load(true)} disabled={loading} aria-label="Пересобрать отчёт"><RefreshCw size={18}/></button></div>{loading&&!data&&<div className="monthly-loading"><TinCharacter small/><strong>Тин разбирает решения…</strong><span>Сверяем сделки и считаем результат на сервере</span></div>}{error&&<div className="news-error"><Info size={18}/><span>{error}</span><button onClick={()=>load()}>Повторить</button></div>}{data&&<><section className="monthly-hero"><span>{data.status==='final'?'Итоговый отчёт':'Предварительный отчёт'}</span><strong>{data.analysis.summary}</strong><small>{data.analysis.method==='gemini'?'Разбор Gemini 2.5':'Разбор по точным метрикам'}</small></section><section className="monthly-metrics"><div><span>Результат продаж</span><strong className={data.metrics.realized_pnl_tkn>=0?'positive':'negative'}>{data.metrics.realized_pnl_tkn>=0?'+':''}{fmt(data.metrics.realized_pnl_tkn,2)} TKN</strong></div><div><span>Потеряно в минусовых продажах</span><strong className="negative">{fmt(data.metrics.money_lost_tkn,2)} TKN</strong></div><div><span>Решений</span><strong>{data.metrics.decisions_count}</strong></div><div><span>Уроков</span><strong>{data.metrics.lessons_completed}</strong></div></section>{data.analysis.strengths?.length>0&&<section className="monthly-section strengths"><h3>Что получилось</h3>{data.analysis.strengths.map((text:string)=><p key={text}>✓ {text}</p>)}</section>}<section className="monthly-section mistakes"><h3>Что можно улучшить</h3>{data.analysis.mistakes?.length?data.analysis.mistakes.map((item:any)=><article key={`${item.title}-${item.related_decision_ids.join()}`}><strong>{item.title}</strong><p>{item.explanation}</p><small>Основано на: {item.related_decision_ids.join(', ')}</small></article>):<p>Подтверждённых ошибок по данным месяца не найдено.</p>}</section><section className="monthly-section next"><h3>План на следующий месяц</h3>{data.analysis.next_steps?.map((text:string,index:number)=><p key={text}><b>{index+1}</b>{text}</p>)}</section><section className="monthly-decisions"><h3>Какие действия учтены</h3>{data.decisions.slice().reverse().slice(0,12).map((item:any)=><div key={item.id}><span><strong>{actionLabel(item)}</strong><small>{new Date(item.at).toLocaleString('ru-RU',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'})}</small></span>{item.kind==='sell'&&<b className={item.game_pnl>=0?'positive':'negative'}>{item.game_pnl>=0?'+':''}{fmt(item.game_pnl,2)} TKN</b>}</div>)}</section><p className="monthly-disclaimer"><ShieldCheck size={17}/>{data.disclaimer}</p></>}</div></SheetShell>
}

function SheetShell({title,children,onClose,wide=false,fullscreen=false}:{title:string;children:any;onClose:()=>void;wide?:boolean;fullscreen?:boolean}){
  return <motion.div className={`sheet-backdrop ${fullscreen?'fullscreen':''}`} initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}} onMouseDown={e=>e.target===e.currentTarget&&onClose()}>
    <motion.section
      className={`sheet ${wide?'wide':''} ${fullscreen?'lesson-screen':''}`}
      initial={fullscreen?{x:'100%'}:{y:'100%'}}
      animate={fullscreen?{x:0}:{y:0}}
      exit={fullscreen?{x:'100%'}:{y:'100%'}}
      transition={{type:'spring',damping:30,stiffness:340}}
    >
      <header><button onClick={onClose} aria-label="Закрыть урок"><ArrowLeft/></button><h2>{title}</h2><span/></header>{children}
    </motion.section>
  </motion.div>
}

function StreakSheet({streakState,onClose,done,refresh}:{streakState:StreakState;onClose:()=>void;done:(s:string)=>void;refresh:()=>void}){
  const [state,setState]=useState<StreakState>(streakState)
  const [busy,setBusy]=useState(false)
  const [clock,setClock]=useState(Date.now())

  useEffect(()=>{setState(streakState)},[streakState])
  useEffect(()=>{
    api<StreakState>('/streak').then(setState).catch((e:any)=>done(e.message))
  },[done])
  useEffect(()=>{
    if(!state.claimed_today)return
    const timer=window.setInterval(()=>setClock(Date.now()),1000)
    return ()=>window.clearInterval(timer)
  },[state.claimed_today])

  const remaining=state.claimed_today?Math.max(0,Math.ceil((new Date(state.next_claim_at).getTime()-clock)/1000)):0
  const countdown=`${String(Math.floor(remaining/3600)).padStart(2,'0')}:${String(Math.floor((remaining%3600)/60)).padStart(2,'0')}:${String(remaining%60).padStart(2,'0')}`
  const claim = async () => {
    if(busy||state.claimed_today)return
    setBusy(true)
    try {
      const r = await api<StreakState&{message:string}>('/streak/claim', {method: 'POST'})
      done(r.message)
      setState(r)
      await refresh()
    } catch(e:any) {
      done(e.message)
    } finally { setBusy(false) }
  }
  return (
    <SheetShell title="Дни в ритме" onClose={onClose}>
      <div className="sheet-content streak-sheet">
        <div className={`streak-hero ${state.claimed_today?'claimed':'available'}`}>
          <Flame size={64} fill="#ef3124" color="#ef3124"/>
          <strong>{state.streak_count>0?`${state.streak_count} дней подряд`:'Начни серию сегодня'}</strong>
          <p>{state.claimed_today?`Следующий бонус через ${countdown}`:'Отметься сегодня, чтобы сохранить серию и получить бонус.'}</p>
        </div>
        <div className="streak-calendar">
          {state.week.map(day=>(
            <div key={day.date} className={`day-node ${day.status}`} title={new Date(`${day.date}T12:00:00`).toLocaleDateString('ru-RU')}>
              <span>{day.label}</span>
              <i>{day.status==='claimed'?<Check size={14}/>:day.status==='missed'?'×':'•'}</i>
            </div>
          ))}
        </div>
        <div className="streak-reward-card">
          <span>{state.claimed_today?'Сегодня начислено':'Награда за сегодня'}</span>
          <strong>+{state.current_reward.xp} XP · +{state.current_reward.boost} Boost</strong>
        </div>
        <button className="primary" disabled={busy||state.claimed_today} onClick={claim}>
          {busy?'Начисляем…':state.claimed_today?`Получено · следующий бонус через ${countdown}`:'Забрать дневной бонус'}
        </button>
        <section className="streak-totals"><div><span>Всего отметок</span><strong>{state.total_rewards.days}</strong></div><div><span>Получено XP</span><strong>+{state.total_rewards.xp}</strong></div><div><span>Получено Boost</span><strong>+{state.total_rewards.boost}</strong></div></section>
        {state.history.length>0&&<section className="streak-history"><h3>История бонусов</h3>{state.history.slice(0,7).map(item=><div key={item.date}><span><strong>{new Date(`${item.date}T12:00:00`).toLocaleDateString('ru-RU',{day:'numeric',month:'short'})}</strong><small>{new Date(item.claimed_at).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})} · день {item.streak_day}</small></span><b>+{item.xp} XP · +{item.boost} Boost</b></div>)}</section>}
        <small className="streak-timezone">Новый день считается с 00:00 по Москве</small>
      </div>
    </SheetShell>
  )
}

function LessonSheet({lesson,onClose,refresh,done}:{lesson:any;onClose:()=>void;refresh:()=>void;done:(s:string)=>void}){
  const [answers,setAnswers]=useState<Record<number,number>>({})
  const [busy,setBusy]=useState(false)
  const [question,setQuestion]=useState('')
  const [assistantBusy,setAssistantBusy]=useState(false)
  const [assistantMessages,setAssistantMessages]=useState<{question:string;answer:string;points:string[];method:string;model?:string}[]>([])

  const info = LESSON_CONTENT[Number(lesson?.id)] || FALLBACK_LESSON
  const answeredCount = info.quiz.filter((_,index)=>answers[index] !== undefined).length
  const allCorrect = info.quiz.every((item,index)=>answers[index] === item.answer)

  useEffect(()=>setAnswers({}),[lesson?.id])

  const complete = async () => {
    setBusy(true)
    try {
      const r = await api<any>(`/learning/lessons/${lesson.id}/complete`, {
        method: 'POST',
        body: JSON.stringify({answers:info.quiz.map((_,index)=>answers[index] ?? -1)}),
      })
      done(r.already_completed ? 'Урок уже пройден' : `Урок пройден! +${r.xp} XP · +${r.boost} Boost`)
      refresh()
      onClose()
    } catch(e:any) {
      done(e.message)
    } finally {
      setBusy(false)
    }
  }

  const askAssistant=async(value?:string)=>{
    const text=(value??question).trim()
    if(text.length<2||assistantBusy)return
    setQuestion('');setAssistantBusy(true)
    try{
      const result=await api<any>('/learning/assistant',{method:'POST',body:JSON.stringify({lesson_id:lesson.id,question:text})})
      setAssistantMessages(current=>[...current,{question:text,answer:result.answer,points:result.key_points||[],method:result.method,model:result.model}])
    }catch(e:any){done(e.message)}finally{setAssistantBusy(false)}
  }

  return (
    <SheetShell title={lesson?.title || 'Урок'} onClose={onClose} fullscreen>
      <div className="sheet-content lesson-detail">
        <div className="lesson-badge"><span>{lesson?.course}</span><b>+{lesson?.xp_reward} XP</b></div>
        <h2>{lesson?.title}</h2>
        <div className="lesson-meta"><BookOpen size={19}/><span>≈ {info.minutes} минут</span><i/><span>{info.sections.length} смысловых блока</span></div>
        <p className="lesson-text">{info.intro}</p>
        <div className="lesson-sections">
          {info.sections.map((section,index)=><section className="lesson-section" key={section.title}>
            <header><span>{index+1}</span><h3>{section.title}</h3></header>
            {section.paragraphs.map(paragraph=><p key={paragraph}>{paragraph}</p>)}
            {section.example&&<aside><strong>Пример</strong><p>{section.example}</p></aside>}
          </section>)}
        </div>
        <div className="lesson-keys">
          <strong>Главные мысли:</strong>
          <ul>{info.keys.map((k,i)=><li key={i}>✓ {k}</li>)}</ul>
        </div>
        <section className="lesson-assistant">
          <div className="assistant-title"><TinCharacter small/><span><strong>Спроси Тина</strong><small>Он объяснит тему простыми словами и не станет додумывать факты</small></span></div>
          <div className="assistant-suggestions">{['Объясни на примере','Что здесь самое важное?','Какие есть риски?'].map(text=><button key={text} disabled={assistantBusy} onClick={()=>askAssistant(text)}>{text}</button>)}</div>
          {assistantMessages.map((message,index)=><div className="assistant-dialog" key={`${message.question}-${index}`}><p className="assistant-question">{message.question}</p><div className="assistant-reply"><TinCharacter small/><div className="assistant-answer"><p>{message.answer}</p>{message.points.length>0&&<ul>{message.points.map(point=><li key={point}>{point}</li>)}</ul>}<small>Важные факты и цифры лучше перепроверить по материалам урока</small></div></div></div>)}
          <form onSubmit={event=>{event.preventDefault();askAssistant()}}><textarea value={question} maxLength={800} onChange={event=>setQuestion(event.target.value)} placeholder="Например: почему цена акции меняется?"/><button type="submit" disabled={assistantBusy||question.trim().length<2}>{assistantBusy?<RefreshCw size={18}/>:<ChevronRight size={18}/>}</button></form>
        </section>
        <div className="lesson-quiz">
          <header><div><strong>Проверка знаний</strong><span>Нужно ответить верно на все вопросы</span></div><b>{answeredCount}/{info.quiz.length}</b></header>
          {info.quiz.map((item,questionIndex)=>{
            const selected=answers[questionIndex]
            const isCorrect=selected===item.answer
            return <fieldset className="quiz-question" key={item.question}>
              <legend><span>{questionIndex+1}</span>{item.question}</legend>
              <div className="quiz-opts">
                {item.options.map((option,optionIndex)=><button
                  type="button"
                  key={option}
                  className={selected===optionIndex?(isCorrect?'selected correct':'selected wrong'):''}
                  onClick={()=>setAnswers(current=>({...current,[questionIndex]:optionIndex}))}
                >{option}</button>)}
              </div>
              {selected!==undefined&&<small className={isCorrect?'quiz-feedback correct':'quiz-feedback wrong'}>{isCorrect?`Верно. ${item.explanation}`:'Пока неверно. Вернись к разделу выше и попробуй ещё раз.'}</small>}
            </fieldset>
          })}
        </div>
        <button className="primary lesson-complete" disabled={busy || !allCorrect} onClick={complete}>
          {lesson?.completed_at ? 'Пройти повторно' : 'Завершить урок'}
        </button>
      </div>
    </SheetShell>
  )
}

function EditProfileSheet({user,onClose,refresh,done}:{user:any;onClose:()=>void;refresh:()=>void;done:(s:string)=>void}){
  const [name,setName]=useState(user?.display_name || 'Саша')
  const [birthDate,setBirthDate]=useState(user?.birth_date || '2009-05-14')
  const [busy,setBusy]=useState(false)
  const age=ageFromDate(birthDate)
  const validAge=age!==null&&age>=6&&age<=100
  const today=new Date().toISOString().slice(0,10)

  const save = async () => {
    if (!name.trim()||!validAge) return
    setBusy(true)
    try {
      await api('/auth/me', {method: 'PUT', body: JSON.stringify({display_name: name, birth_date: birthDate})})
      done('Профиль успешно обновлён!')
      await refresh()
      onClose()
    } catch(e:any) {
      done(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <SheetShell title="Редактировать профиль" onClose={onClose}>
      <div className="sheet-content edit-profile">
        <label>
          Имя инвестора
          <input value={name} onChange={e=>setName(e.target.value)} placeholder="Твоё имя"/>
        </label>
        <label>
          Дата рождения
          <input type="date" min="1926-01-01" max={today} value={birthDate} onChange={e=>setBirthDate(e.target.value)}/>
        </label>
        <div className={`age-preview ${validAge?'valid':'invalid'}`}><span>{validAge?`Тебе ${age} ${yearsWord(age!)}`:'Проверь дату рождения'}</span><strong>{validAge&&(age??0)>=18?'Раздел будет называться «Ток»':'Раздел будет называться «Тин-Ток»'}</strong></div>
        <button className="primary" disabled={busy || !name.trim() || !validAge} onClick={save}>
          Сохранить изменения
        </button>
      </div>
    </SheetShell>
  )
}

function SecuritySheet({user,onClose,done}:{user:any;onClose:()=>void;done:(s:string)=>void}){
  const [currentPassword,setCurrentPassword]=useState('')
  const [newPassword,setNewPassword]=useState('')
  const [confirmPassword,setConfirmPassword]=useState('')
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(false)
  const canSubmit=currentPassword.length>0&&newPassword.length>=6&&newPassword===confirmPassword&&newPassword!==currentPassword

  const changePassword=async(event:React.FormEvent)=>{
    event.preventDefault()
    if(newPassword!==confirmPassword){setError('Новые пароли не совпадают');return}
    if(newPassword===currentPassword){setError('Новый пароль должен отличаться от текущего');return}
    setBusy(true)
    setError('')
    try{
      const result=await api<any>('/auth/password',{method:'POST',body:JSON.stringify({current_password:currentPassword,new_password:newPassword})})
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      done(result.message||'Пароль изменён')
    }catch(e:any){setError(e.message)}finally{setBusy(false)}
  }

  return <SheetShell title="Безопасность" onClose={onClose}><div className="sheet-content security-sheet">
    <section className="security-hero"><ShieldCheck size={34}/><div><span>Защита аккаунта</span><strong>Локальная авторизация включена</strong><p>До подключения Alfa ID вход выполняется по имени и паролю.</p></div></section>
    <div className="security-facts">
      <article><LockKeyhole size={20}/><div><strong>Пароль хранится как bcrypt-хеш</strong><span>Сам пароль не записывается в базу в открытом виде.</span></div></article>
      <article><CircleUserRound size={20}/><div><strong>{user?.display_name||'Пользователь'} · {user?.public_id||user?.referral_code||''}</strong><span>Друзья видят имя, публичный ID, игровой капитал, позиции и опубликованные посты.</span></div></article>
      <article><Banknote size={20}/><div><strong>Реальные деньги не подключены</strong><span>TKN, AC и CT существуют только внутри учебного симулятора.</span></div></article>
    </div>
    <form className="security-password" onSubmit={changePassword}>
      <header><span>Сменить пароль</span><p>После изменения текущая сессия останется активной. Для повторного входа понадобится новый пароль.</p></header>
      <label>Текущий пароль<input type="password" autoComplete="current-password" value={currentPassword} onChange={event=>setCurrentPassword(event.target.value)} required/></label>
      <label>Новый пароль<input type="password" autoComplete="new-password" minLength={6} maxLength={72} value={newPassword} onChange={event=>setNewPassword(event.target.value)} placeholder="Минимум 6 символов" required/></label>
      <label>Повтори новый пароль<input type="password" autoComplete="new-password" minLength={6} maxLength={72} value={confirmPassword} onChange={event=>setConfirmPassword(event.target.value)} required/></label>
      {confirmPassword&&newPassword!==confirmPassword&&<p className="security-error">Новые пароли не совпадают</p>}
      {error&&<p className="security-error">{error}</p>}
      <button className="primary" disabled={busy||!canSubmit}>{busy?'Меняем пароль…':'Изменить пароль'}</button>
    </form>
    <p className="security-note"><Info size={16}/>Серверного завершения всех ранее выданных сессий пока нет. Эта возможность появится вместе с Alfa ID.</p>
  </div></SheetShell>
}

function PortfolioSheet({data,allTimeChangePct=0,onClose,onShare}:{data:any;allTimeChangePct?:number;onClose:()=>void;onShare:(trade:any)=>void}){
  const [historyData,setHistoryData]=useState<any[]>([])
  const [trades,setTrades]=useState<any[]>([])
  useEffect(()=>{
    api<any[]>('/portfolio/history').then(setHistoryData).catch(()=>{})
    api<any[]>('/portfolio/trades').then(setTrades).catch(()=>{})
  },[])
  const chartPoints = useMemo(()=>{
    if (historyData.length > 0) return historyData.map((h,i)=>({t: h.date?.slice(5) || `d${i}`, v: h.value}))
    return [{t: '0', v: data?.net_worth || 1000}]
  },[historyData, data?.net_worth])

  const cash=Number(data?.cash||0); const stocks=Number(data?.stocks||0); const funds=Number(data?.funds||0); const piggy=Number(data?.piggy||0); const total=Number(data?.net_worth||0); const eligible=Number(data?.eligible_profit||0)
  const buckets=[{label:'На счету',value:cash,icon:<Banknote/>},{label:'В акциях',value:stocks,icon:<LineChart/>},{label:'В фондах',value:funds,icon:<PieChart/>},{label:'В копилке',value:piggy,icon:<PiggyBank/>}]
  return <SheetShell title="Кошелёк" onClose={onClose} wide><div className="sheet-content wallet-sheet"><section className="portfolio-total"><span>ВСЕГО В TKN</span><strong>{fmt(total,2)} TKN</strong><em className={allTimeChangePct>=0?'positive':'negative'}>{allTimeChangePct>=0?'+':''}{fmt(allTimeChangePct,1)}% за всё время</em><div className="portfolio-chart"><ResponsiveContainer width="100%" height="100%"><AreaChart data={chartPoints}><defs><linearGradient id="area" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#ef3124" stopOpacity=".26"/><stop offset="1" stopColor="#ef3124" stopOpacity="0"/></linearGradient></defs><Area dataKey="v" stroke="#ef3124" strokeWidth={3} fill="url(#area)"/><Tooltip/></AreaChart></ResponsiveContainer></div></section><div className="wallet-buckets">{buckets.map(bucket=><article key={bucket.label}>{bucket.icon}<span>{bucket.label}</span><strong>{fmt(bucket.value,2)} TKN</strong>{bucket.label==='На счету'&&<small>можно потратить</small>}</article>)}</div><section className="portfolio-explainer"><TinCharacter small/><div><span>Как считается</span><strong>{fmt(cash,2)} + {fmt(stocks,2)} + {fmt(funds,2)} + {fmt(piggy,2)} = {fmt(total,2)} TKN</strong><p>Свободные деньги, акции, фонды и инвесткопилка показаны отдельно.</p><small>Из денег на счету {fmt(eligible,2)} TKN доступны к обмену на AC; второй раз в итог они не прибавляются.</small></div></section><h3 className="sheet-title">Позиции</h3><div className="position-list">{data?.positions?.map((p:any)=><div key={p.id}><div className="ticker-logo">{p.ticker.slice(0,2)}</div><span><strong>{p.ticker}</strong><em>{p.type==='fund'?'Фонд':'Акция'} · {fmt(p.quantity,2)} шт.</em></span><b>{fmt(p.game_value,2)} TKN<em className={p.game_pnl>=0?'positive':'negative'}>{p.game_pnl>=0?'+':''}{fmt(p.game_pnl,2)}</em></b></div>)}</div>{trades.some(trade=>trade.side==='sell'&&Number(trade.game_pnl)>0)&&<><h3 className="sheet-title">Удачные транзакции</h3><div className="shareable-trades">{trades.filter(trade=>trade.side==='sell'&&Number(trade.game_pnl)>0).slice(0,5).map(trade=><article key={trade.id}><div><strong>Продажа {trade.ticker}</strong><small>Результат +{fmt(trade.game_pnl,2)} TKN</small></div><button onClick={()=>onShare({...trade,quote_tkn:Number(trade.raw_quote_tkn)})}><Send size={16}/>В Тин-Ток</button></article>)}</div></>}</div></SheetShell>
}

function ConvertSheet({conversion,onClose,done,refresh}:{conversion:any;onClose:()=>void;done:(s:string)=>void;refresh:()=>void}){
  const eligible=Number(conversion?.eligible||0)
  const [tokens,setTokens]=useState(Math.min(100,eligible))
  const [preview,setPreview]=useState<any>(null)
  const [busy,setBusy]=useState(false)
  useEffect(()=>{
    if(tokens<=0){setPreview(null);return}
    const timer=window.setTimeout(()=>api<any>('/economy/conversion/preview',{method:'POST',body:JSON.stringify({tokens})}).then(setPreview).catch(()=>setPreview(null)),180)
    return ()=>window.clearTimeout(timer)
  },[tokens])
  const rate=Number(preview?.rate??conversion?.rate??50)
  const base=Number(preview?.base_ac??0)
  const bonus=Number(preview?.boost_ac??0)
  const total=Number(preview?.total_ac??0)
  const capRemaining=Number(conversion?.caps?.total?.remaining??15000)
  const submit=async()=>{setBusy(true);try{const r=await api<any>('/economy/convert',{method:'POST',body:JSON.stringify({tokens})});done(`Получено ${fmt(r.received)} AC за ${fmt(r.burned,2)} TKN`);await refresh();onClose()}catch(e:any){done(e.message)}finally{setBusy(false)}}
  return <SheetShell title="Получить Alfa Coins" onClose={onClose}><div className="sheet-content convert"><p>Обменять можно зафиксированную прибыль от рынка и начисленный доход накопительного счёта.</p><div className="convert-balance"><span>Доступно к обмену</span><strong>{fmt(eligible,2)} TKN</strong><em>1 TKN = {fmt(rate,2)} AC</em></div><section className="conversion-policy"><div><strong>Курс зависит от капитала</strong><span>Расчётная база за 30 дней: {fmt(conversion?.rolling_net_worth||0,0)} TKN</span></div><p>При росте капитала AC за один TKN становится меньше, но общая скорость заработка продолжает расти. Минимальный курс — {fmt(conversion?.rate_floor||5)} AC за TKN.</p><footer><span>Лимит на 30 дней</span><b>осталось {fmt(capRemaining)} AC</b></footer></section><label>Сколько обменять<input type="number" min="0.01" step="0.01" max={eligible} value={tokens} onChange={e=>setTokens(Math.max(0,Number(e.target.value)))}/></label><div className="preset-row">{[.1,.25,.5,1].map((p,i)=><button key={p} onClick={()=>setTokens(Number((eligible*p).toFixed(2)))}>{i===3?'MAX':`${p*100}%`}</button>)}</div><div className="receipt"><div><span>База</span><b>{fmt(base)} AC</b></div><div><span>Бонус за активность</span><b className="positive">+{fmt(bonus)} AC</b></div><div className="total"><span>Итого</span><b>{fmt(total)} AC</b></div></div><button className="primary" disabled={busy||!preview||total<=0||tokens>eligible} onClick={submit}>{busy?'Обмениваем…':`Получить ${fmt(total)} AC`}</button></div></SheetShell>
}

type CartItem = { item: any; quantity: number }

function ShopSheet({items,coins,goalId,onClose,refresh,done}:{items:any[];coins:number;goalId?:number;onClose:()=>void;refresh:()=>void;done:(s:string)=>void}){
  const [view,setView]=useState<'catalog'|'cart'>('catalog')
  const [cart,setCart]=useState<CartItem[]>([])
  const [busy,setBusy]=useState(false)

  const addToCart = (item:any) => {
    setCart(prev => {
      const idx = prev.findIndex(c => c.item.id === item.id)
      if (idx >= 0) {
        const next = [...prev]
        next[idx] = { ...next[idx], quantity: next[idx].quantity + 1 }
        return next
      }
      return [...prev, { item, quantity: 1 }]
    })
    done(`${item.name} добавлен в корзину`)
  }

  const updateCartQty = (itemId:number, delta:number) => {
    setCart(prev => {
      return prev.map(c => {
        if (c.item.id === itemId) {
          const q = c.quantity + delta
          return q > 0 ? { ...c, quantity: q } : null
        }
        return c
      }).filter(Boolean) as CartItem[]
    })
  }

  const setGoal = async (item:any) => {
    try {
      await api('/shop/goal', {method: 'PUT', body: JSON.stringify({shop_item_id: item.id})})
      done(`${item.name} — новая цель`)
      refresh()
    } catch(e:any) {
      done(e.message)
    }
  }

  const cartTotal = useMemo(() => cart.reduce((sum, c) => sum + c.item.price_ac * c.quantity, 0), [cart])
  const totalCount = useMemo(() => cart.reduce((sum, c) => sum + c.quantity, 0), [cart])

  const checkoutCart = async () => {
    if (cart.length === 0) return
    if (coins < cartTotal) {
      done(`Не хватает Alfa Coins! У вас ${fmt(coins)} AC, нужно ${fmt(cartTotal)} AC.`)
      return
    }
    setBusy(true)
    try {
      const payload = { items: cart.map(c => ({ shop_item_id: c.item.id, quantity: c.quantity })) }
      const r = await api<any>('/shop/orders/cart', {method: 'POST', body: JSON.stringify(payload)})
      done(r.message || 'Заказ оформлен!')
      setCart([])
      refresh()
      setView('catalog')
    } catch(e:any) {
      done(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <SheetShell title="Магазин" onClose={onClose} wide>
      <div className="sheet-content">
        <div className="shop-top-bar">
          <div className="shop-balance">
            <span>Твой баланс</span>
            <strong>{fmt(coins)} AC</strong>
          </div>
          <div className="shop-view-toggle">
            <button className={view==='catalog'?'active':''} onClick={()=>setView('catalog')}>Каталог</button>
            <button className={view==='cart'?'active':''} onClick={()=>setView('cart')}>
              Корзина {totalCount > 0 && <span className="cart-badge">{totalCount}</span>}
            </button>
          </div>
        </div>

        {view === 'catalog' ? (
          <div className="shop-grid">
            {items.map(item => {
              const inCart = cart.find(c => c.item.id === item.id)
              const pct = Math.min(100, (coins / item.price_ac) * 100)
              return (
                <article key={item.id} className={goalId===item.id?'goal-item':''}>
                  <div className="merch-art">
                    <img src={`/assets/merch/${item.slug}.webp`} alt={item.name}/>
                    {goalId===item.id && <em><Target size={14}/>Цель</em>}
                  </div>
                  <h3>{item.name}</h3>
                  <p>{item.description}</p>
                  <strong>{fmt(item.price_ac)} AC</strong>
                  <div className="progress"><i style={{width:`${pct}%`}}/></div>
                  <div className="shop-item-actions">
                    <button className="primary-btn" onClick={()=>addToCart(item)}>
                      {inCart ? `В корзине (${inCart.quantity})` : 'В корзину'}
                    </button>
                    {goalId !== item.id && (
                      <button className="text-btn" onClick={()=>setGoal(item)}>Выбрать целью</button>
                    )}
                  </div>
                </article>
              )
            })}
          </div>
        ) : (
          <div className="cart-view">
            {cart.length === 0 ? (
              <div className="empty-cart">
                <ShoppingBag size={48}/>
                <p>Корзина пуста. Добавьте товары из каталога.</p>
                <button className="primary" onClick={()=>setView('catalog')}>К каталогу</button>
              </div>
            ) : (
              <>
                <div className="cart-items-list">
                  {cart.map(c => (
                    <div key={c.item.id} className="cart-row">
                      <img className="cart-product-image" src={`/assets/merch/${c.item.slug}.webp`} alt=""/>
                      <div className="cart-meta">
                        <strong>{c.item.name}</strong>
                        <span>{fmt(c.item.price_ac)} AC / шт.</span>
                      </div>
                      <div className="qty-controls">
                        <button onClick={()=>updateCartQty(c.item.id, -1)}>-</button>
                        <b>{c.quantity}</b>
                        <button onClick={()=>updateCartQty(c.item.id, 1)}>+</button>
                      </div>
                      <strong className="cart-subtotal">{fmt(c.item.price_ac * c.quantity)} AC</strong>
                    </div>
                  ))}
                </div>

                <div className="cart-summary">
                  <div><span>Доступно:</span><b>{fmt(coins)} AC</b></div>
                  <div className="total"><span>Итого к оплате:</span><b>{fmt(cartTotal)} AC</b></div>
                </div>

                <button 
                  className="primary checkout-btn" 
                  disabled={busy || cartTotal > coins} 
                  onClick={checkoutCart}
                >
                  {cartTotal > coins ? 'Не хватает Alfa Coins' : `Оформить заказ на ${fmt(cartTotal)} AC`}
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </SheetShell>
  )
}

function ShareTradeSheet({trade,onClose,onPublished,done}:{trade:any;onClose:()=>void;onPublished:()=>void;done:(text:string)=>void}){
  const [comment,setComment]=useState(trade?.is_first_purchase?`Моя первая покупка — @${trade.ticker}. Начинаю с небольшой суммы.`:`Сегодня смотрел на @${trade.ticker} и придерживался своего плана.`)
  const [busy,setBusy]=useState(false)
  const publish=async()=>{setBusy(true);try{const result=await api<any>('/social/posts',{method:'POST',body:JSON.stringify({comment})});done(result.message);onPublished();onClose()}catch(e:any){done(e.message)}finally{setBusy(false)}}
  return <SheetShell title="Поделиться в Тин-Токе" onClose={onClose}><div className="sheet-content share-trade-sheet"><div className="share-celebration"><TinCharacter small/><div><span>{trade?.is_first_purchase?'ПЕРВАЯ ПОКУПКА':'НОВЫЙ ПОСТ'}</span><strong>Хочешь рассказать друзьям?</strong><p>Пост появится только после твоего подтверждения.</p></div></div><div className="mention-preview"><b>@{trade.ticker}</b><span>К посту прикрепится ссылка на инструмент, данные транзакции останутся приватными.</span></div><label>Комментарий<textarea maxLength={300} value={comment} onChange={event=>setComment(event.target.value)} placeholder={`Напиши мнение и оставь @${trade.ticker}, чтобы прикрепить инструмент`}/><small>{comment.length}/300</small></label><button className="primary" disabled={busy||!comment.trim()} onClick={publish}><Send size={18}/>{busy?'Публикуем…':'Опубликовать'}</button><button className="secondary" onClick={onClose}>Не сейчас</button></div></SheetShell>
}

function InstrumentSheet({instrument,onClose,refresh,done,onShare}:{instrument:Instrument;onClose:()=>void;refresh:()=>void;done:(s:string)=>void;onShare:(trade:any)=>void}){
  const [details,setDetails]=useState<Instrument>(instrument); const [qty,setQty]=useState(1); const [busy,setBusy]=useState(false)
  useEffect(()=>{api<Instrument>(`/market/instruments/${instrument.id}`).then(setDetails)},[instrument.id])
  const trade=async(side:'buy'|'sell')=>{setBusy(true);try{const r=await api<any>(`/trades/${side}`,{method:'POST',headers:{'Idempotency-Key':crypto.randomUUID()},body:JSON.stringify({instrument_id:instrument.id,quantity:qty})});done(`${r.message}${side==='sell'?` · результат ${fmt(r.game_pnl,2)} TKN`:''}`);await refresh();if(r.share_prompt)onShare(r);else onClose()}catch(e:any){done(e.message)}finally{setBusy(false)}}
  return <SheetShell title={details.name} onClose={onClose} wide><div className="sheet-content instrument-detail"><div className="instrument-heading"><div className="ticker-logo large">{details.ticker.slice(0,2)}</div><div><span>{details.ticker} · {details.sector}</span><strong>{fmt(details.display_price_tkn,2)} TKN</strong><em className={details.change_pct>=0?'positive':'negative'}>{details.change_pct>=0?'+':''}{fmt(details.change_pct,2)}% сегодня</em></div></div><div className="chart-big"><ResponsiveContainer width="100%" height="100%"><AreaChart data={details.candles||[]}><defs><linearGradient id="chartFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#ef3124" stopOpacity=".28"/><stop offset="1" stopColor="#ef3124" stopOpacity="0"/></linearGradient></defs><XAxis dataKey="t" hide/><Tooltip/><Area dataKey="v" stroke="#ef3124" strokeWidth={3} fill="url(#chartFill)"/></AreaChart></ResponsiveContainer></div><div className="quote-meta"><span>{fmt(details.real_price_rub,2)} ₽ на Мосбирже</span><StatusDot live={details.source==='finam'}/></div><div className="info-box"><Zap size={20}/><div><strong>Игровой эффект ×10</strong><p>Котировка настоящая, но результат позиции двигается быстрее, чтобы стратегия была заметна за недели.</p></div></div><div className="instrument-copy"><span>Что это</span><p>{details.description}. Риск: {details.risk_level.toLowerCase()}.</p></div>{details.position&&<div className="your-position"><span>Твоя позиция</span><strong>{fmt(details.position.quantity,2)} шт.</strong><em>Средняя: {fmt(details.position.average_buy_token_price,2)} TKN</em></div>}<label className="qty">Количество<input type="number" min="0.0001" step="0.1" value={qty} onChange={e=>setQty(Number(e.target.value))}/></label><div className="trade-actions"><button className="primary" disabled={busy||qty<=0} onClick={()=>trade('buy')}><ArrowDown/>Купить</button><button className="secondary" disabled={busy||!details.position||qty<=0} onClick={()=>trade('sell')}><ArrowUp/>Продать</button></div><small className="disclaimer">Сделка игровая и не отправляется брокеру.</small></div></SheetShell>
}

function PiggySheet({data,onClose,refresh,done}:{data:any;onClose:()=>void;refresh:()=>void;done:(s:string)=>void}){
 const [amount,setAmount]=useState(25); const move=async(type:'deposit'|'withdraw')=>{try{const r=await api<any>(`/piggy/${type}`,{method:'POST',body:JSON.stringify({amount})});done(`В копилке ${fmt(r.balance,2)} TKN`);refresh()}catch(e:any){done(e.message)}}
 return <SheetShell title="Инвесткопилка" onClose={onClose}><div className="sheet-content piggy"><div className="piggy-visual"><PiggyBank size={74}/><span>В копилке</span><strong>{fmt(data?.balance_tkn||0,2)} TKN</strong></div><div className="rate-line"><span>Ставка сегодня</span><strong>{fmt(Number(data?.current_apr||0)*100,1)}% годовых</strong></div><p>Начисление за день: ≈ {fmt(data?.daily_yield||0,2)} TKN. Положить можно любую сумму из свободных TKN.</p><p className="piggy-economy-note"><Info size={17}/>Начисленный доход приходит на основной счёт и сразу становится доступен для обмена на Alfa Coins. Сама сумма вклада остаётся в копилке.</p><label>Сумма<input type="number" min="0.01" step="0.01" value={amount} onChange={e=>setAmount(Number(e.target.value))}/></label><div className="trade-actions"><button className="primary" onClick={()=>move('deposit')}>Положить</button><button className="secondary" onClick={()=>move('withdraw')}>Забрать</button></div></div></SheetShell>
}

function PortfolioNewsSheet({onClose}:{onClose:()=>void}){
  const [data,setData]=useState<any>()
  const [loading,setLoading]=useState(true)
  const [error,setError]=useState('')

  const load=async(force=false)=>{
    setLoading(true);setError('')
    try{
      const result=await api<any>(force?'/news/portfolio-insights/refresh':'/news/portfolio-insights',{method:force?'POST':'GET'})
      setData(result)
    }catch(e:any){setError(e.message||'Не удалось загрузить новости')}
    finally{setLoading(false)}
  }

  useEffect(()=>{load()},[])
  const sourceState=(value:string,count:number)=>value==='confirmed'?{label:`Подтверждено · ${count} источника`,className:'confirmed'}:value==='conflicting'?{label:'Источники расходятся',className:'conflicting'}:{label:'Пока один источник',className:'single'}

  return <SheetShell title="Новости компаний" onClose={onClose} wide><div className="sheet-content news-insights">
    <div className="news-intro"><div><span>3–4 КОМПАНИИ ИЗ ПОРТФЕЛЯ</span><strong>События, а не прогнозы</strong></div><button onClick={()=>load(true)} disabled={loading} aria-label="Обновить новости"><RefreshCw size={18}/></button></div>
    {loading&&!data&&<div className="news-loading"><RefreshCw/><strong>Сверяем новости компаний…</strong><span>Ищем одно событие в нескольких достоверных источниках</span></div>}
    {error&&<div className="news-error"><Info size={18}/><span>{error}</span><button onClick={()=>load()}>Повторить</button></div>}
    {!loading&&data?.items?.length===0&&<div className="news-empty"><Newspaper/><strong>В портфеле пока нет активов</strong><span>После первой покупки здесь появятся связанные новости.</span></div>}
    {data?.items?.map((item:any)=>{const state=sourceState(item.insight.source_agreement,item.insight.source_count||0);return <article className="news-card event-card" key={item.instrument.id}>
      <header><div className="ticker-logo">{item.instrument.ticker.slice(0,2)}</div><div><span>{item.instrument.ticker} · {fmt(item.instrument.real_price_rub,2)} ₽</span><strong>{item.instrument.name}</strong></div><Newspaper size={20}/></header>
      <div className={`source-check ${state.className}`}><ShieldCheck size={16}/><span>{state.label}</span></div>
      <h3>{item.insight.headline}</h3><p>{item.insight.event_summary}</p>
      {item.insight.facts?.length>0&&<section className="event-facts"><span>Что известно</span>{item.insight.facts.map((text:string)=><p key={text}>• {text}</p>)}</section>}
      <section className="business-conclusion"><span>Что это значит для бизнеса</span><p>{item.insight.conclusion}</p></section>
      <div className="news-sources"><span>Источники</span>{item.articles.slice(0,4).map((article:any)=><a href={article.url} target="_blank" rel="noreferrer" key={`${article.url}-${article.title}`}><div><strong>{article.title}</strong><small>{article.source} · {new Date(article.published_at).toLocaleDateString('ru-RU')}</small></div><ExternalLink size={15}/></a>)}</div>
    </article>})}
    {data?.disclaimer&&<p className="news-disclaimer"><ShieldCheck size={17}/>{data.disclaimer}</p>}
  </div></SheetShell>
}

function ContestSheet({data,onClose,refresh,done}:{data:any;onClose:()=>void;refresh:()=>void;done:(s:string)=>void}){
 const [form,setForm]=useState({full_name:'Саша Альфов',ege_year:2026,ege_subject:'Математика',ege_score:82,certificate_mock:'DEMO-2026-001',consent:true}); const apply=async()=>{try{const r=await api<any>('/contest/apply',{method:'POST',body:JSON.stringify(form)});done(r.status==='verified_mock'?'Contest открыт: +1 000 CT':'Нужен результат от 70 баллов');refresh()}catch(e:any){done(e.message)}}; const unlocked=data?.profile?.verification_status==='verified_mock'
 return <SheetShell title="Contest" onClose={onClose}><div className="sheet-content contest">{unlocked?<><div className="contest-wallet"><Trophy/><span>Contest wallet</span><strong>{fmt(data.contest_tokens)} CT</strong><em>Не смешивается с TKN и AC</em></div><h3>Лидерборд · скоро</h3>{data.leaderboard?.map((row:any,i:number)=><div className="leader" key={row.name}><b>{i+1}</b><span>{row.name}</span><em>+{row.return}%</em></div>)}</>:<><div className="contest-lock"><LockKeyhole/><strong>Соревновательный режим</strong><p>Пройди демонстрационную проверку результата ЕГЭ и получи отдельные 1 000 CT.</p></div><label>ФИО<input value={form.full_name} onChange={e=>setForm({...form,full_name:e.target.value})}/></label><div className="form-row"><label>Год<input type="number" value={form.ege_year} onChange={e=>setForm({...form,ege_year:Number(e.target.value)})}/></label><label>Балл<input type="number" value={form.ege_score} onChange={e=>setForm({...form,ege_score:Number(e.target.value)})}/></label></div><label>Предмет<input value={form.ege_subject} onChange={e=>setForm({...form,ege_subject:e.target.value})}/></label><label className="consent"><input type="checkbox" checked={form.consent} onChange={e=>setForm({...form,consent:e.target.checked})}/><span>Согласен на демо-проверку для прототипа</span></label><button className="primary" onClick={apply}>Подать заявку</button></>}</div></SheetShell>
}

function ReferralSheet({onClose,done}:{onClose:()=>void;done:(s:string)=>void}){const [data,setData]=useState<any>();useEffect(()=>{api('/referrals/share').then(setData)},[]);const copy=()=>{navigator.clipboard?.writeText(data?.link);done('Ссылка скопирована')};return <SheetShell title="Пригласить друга" onClose={onClose}><div className="sheet-content referral"><div className="invite-art"><Star/><Star/><Star/></div><h3>Учиться интереснее вместе</h3><p>Друг получит 50 TKN после первой покупки, ты — 100 TKN. Награда не конвертируется напрямую в AC.</p><div className="ref-code"><span>Твой код</span><strong>{data?.code||'TIN-SASHA'}</strong></div><button className="primary" onClick={copy}>Скопировать ссылку</button><small>Осталось наград в этом месяце: {data?.remaining_rewarded_invites||3}</small></div></SheetShell>}

function Onboarding({finish}:{finish:()=>void}){
  const [step,setStep]=useState(0)
  const slides=[
    {kicker:'АЛЬФА ТИН',title:'Твои первые инвестиции. Без первого риска.',text:'Получишь 1 000 игровых TKN и попробуешь настоящие рыночные решения.',art:<TinCharacter/>},
    {kicker:'РЫНОК',title:'Котировки настоящие. Ошибки — игровые.',text:'Цена берётся с Московской биржи, а результат ускорен ×10, чтобы его было видно.',art:<div className="onboarding-chart"><LineChart/><i/><i/><i/></div>},
    {kicker:'ЦЕЛЬ',title:'Прибыль приближает к вещи, которую хочется.',text:'Фиксируй положительный результат, получай Alfa Coins и двигайся к худи.',art:<div className="onboarding-hoodie">🧥<span>20 000 AC</span></div>},
  ]
  const next=()=>{if(step<slides.length-1)setStep(step+1);else finish()}
  return <motion.div className="onboarding" initial={{opacity:0}} animate={{opacity:1}}><div className="onboarding-top"><AlfaMark/><button onClick={finish}>Пропустить</button></div><AnimatePresence mode="wait"><motion.section key={step} initial={{opacity:0,x:25}} animate={{opacity:1,x:0}} exit={{opacity:0,x:-25}}><div className="onboarding-art">{slides[step].art}</div><span>{slides[step].kicker}</span><h1>{slides[step].title}</h1><p>{slides[step].text}</p></motion.section></AnimatePresence><footer><div>{slides.map((_,i)=><i key={i} className={i===step?'active':''}/>)}</div><button onClick={next}>{step===slides.length-1?'Выбрать худи целью':'Дальше'}<ChevronRight/></button></footer></motion.div>
}

function AuthenticatedApp({onLogout}:{onLogout:()=>void}){
  const [page,setPage]=useState<Page>('home'); const [sheet,setSheet]=useState<Sheet>(null); const [selected,setSelected]=useState<Instrument|null>(null); const [selectedLesson,setSelectedLesson]=useState<any>(null); const [selectedSocialUser,setSelectedSocialUser]=useState<number|null>(null); const [selectedShareTrade,setSelectedShareTrade]=useState<any>(null); const [socialVersion,setSocialVersion]=useState(0); const [error,setError]=useState(''); const [toast,setToast]=useState(''); const [loading,setLoading]=useState(true)
  const [dashboard,setDashboard]=useState<any>({wallet:{},user:{}}); const [instruments,setInstruments]=useState<Instrument[]>([]); const [portfolio,setPortfolio]=useState<any>(); const [conversion,setConversion]=useState<any>(); const [items,setItems]=useState<any[]>([]); const [lessons,setLessons]=useState<any[]>([]); const [quests,setQuests]=useState<any[]>([]); const [achievements,setAchievements]=useState<any[]>([]); const [pet,setPet]=useState<any>(); const [piggy,setPiggy]=useState<any>(); const [contest,setContest]=useState<any>(); const [showOnboarding,setShowOnboarding]=useState(false)
  const missionDay=new Date().toLocaleDateString('sv-SE',{timeZone:'Europe/Moscow'})
  const [marketMissionTarget,setMarketMissionTarget]=useState<number|null>(null)
  const [marketMissionDone,setMarketMissionDone]=useState(()=>localStorage.getItem('alfa-tin-volatile-mission')===missionDay)
  const [learnInitialMode,setLearnInitialMode]=useState<'path'|'quests'>('path')
  const notify=useCallback((message:string)=>{setToast(message);window.setTimeout(()=>setToast(''),2800)},[])
  const refresh=useCallback(async()=>{try{const pg=await api('/piggy');const [d,m,p,c,s,l,q,a,t,ct]=await Promise.all([api('/dashboard'),api('/market/instruments'),api('/portfolio'),api('/economy/conversion'),api('/shop/items'),api('/learning/courses'),api('/quests/daily'),api('/achievements'),api('/tamagotchi'),api('/contest')]);setDashboard(d);setInstruments(m as Instrument[]);setPortfolio(p);setConversion(c);setItems(s as any[]);setLessons(l as any[]);setQuests(q as any[]);setAchievements(a as any[]);setPet(t);setPiggy(pg);setContest(ct);setShowOnboarding(!d.user?.onboarding_completed);setError('')}catch(e:any){setError('Backend недоступен. Запусти API на порту 8000.');console.error(e)}finally{setLoading(false)}},[])
  useEffect(()=>{refresh()},[refresh])
  useEffect(()=>{
    let socket:WebSocket|undefined
    let reconnectTimer:number|undefined
    let stopped=false

    const connect=()=>{
      socket=new WebSocket(getMarketWebSocketUrl())
      socket.onmessage=(event)=>{
        try{
          const message=JSON.parse(event.data)
          if(message.type!=='quotes'||!Array.isArray(message.data))return
          const updates=new Map<number,Instrument>(message.data.map((item:Instrument)=>[item.id,item]))
          const live=message.data.some((item:Instrument)=>item.source==='finam')
          setInstruments(current=>current.map(item=>updates.has(item.id)?{...item,...updates.get(item.id)!}:item))
          setDashboard((current:any)=>({...current,market_status:{label:live?'Live':'Демо-данные',timestamp:message.timestamp,live}}))
        }catch(error){console.error('Некорректное сообщение market WebSocket',error)}
      }
      socket.onclose=()=>{
        if(!stopped)reconnectTimer=window.setTimeout(connect,3000)
      }
      socket.onerror=()=>socket?.close()
    }

    connect()
    return ()=>{
      stopped=true
      if(reconnectTimer)window.clearTimeout(reconnectTimer)
      socket?.close()
    }
  },[])
  
  const open=(next:Sheet)=>{
    setSheet(next)
    if (next === 'portfolio') {
      api('/quests/progress', {method: 'POST', body: JSON.stringify({quest_action: 'portfolio_view'})}).then(refresh).catch(()=>{})
    }
  }
  const close=()=>setSheet(null)

  const navigatePage=(next:Page)=>{
    if(next==='learn')setLearnInitialMode('path')
    setPage(next)
  }

  useEffect(()=>{
    const allowed:Page[]=['home','market','tin','learn','social','profile']
    const navigateFromHost=(event:Event)=>{
      const next=(event as CustomEvent<Page>).detail
      if(allowed.includes(next))navigatePage(next)
    }
    const refreshFromHost=()=>{refresh()}
    window.addEventListener('alfa-plugin-navigate',navigateFromHost)
    window.addEventListener('alfa-plugin-refresh',refreshFromHost)
    return()=>{
      window.removeEventListener('alfa-plugin-navigate',navigateFromHost)
      window.removeEventListener('alfa-plugin-refresh',refreshFromHost)
    }
  },[refresh])

  useEffect(()=>{emitPluginEvent('ROUTE_CHANGED',{page})},[page])

  const openQuests=()=>{
    setLearnInitialMode('quests')
    setPage('learn')
    requestAnimationFrame(()=>{window.scrollTo({top:0});document.querySelector('.phone-shell')?.scrollTo({top:0})})
  }

  const startMarketMission=()=>{
    const target=[...instruments].filter(item=>item.type==='stock').sort((a,b)=>Math.abs(b.change_pct)-Math.abs(a.change_pct))[0]
    if(!target){notify('Котировки ещё загружаются — попробуй через несколько секунд');return}
    setMarketMissionTarget(target.id)
    setPage('market')
    requestAnimationFrame(()=>{window.scrollTo({top:0});document.querySelector('.phone-shell')?.scrollTo({top:0})})
  }
  
  const select=(item:Instrument)=>{
    if(marketMissionTarget!==null&&item.type==='stock'){
      if(item.id!==marketMissionTarget){
        notify('Не она: сравни проценты без знака + или −. Чем число дальше от нуля, тем сильнее движение.')
        return
      }
      localStorage.setItem('alfa-tin-volatile-mission',missionDay)
      setMarketMissionDone(true)
      setMarketMissionTarget(null)
      notify(`${item.ticker} — верно! Это самое сильное движение в текущем списке.`)
    }
    setSelected(item)
    setSheet('instrument')
    api('/quests/progress', {method: 'POST', body: JSON.stringify({quest_action: 'company_view'})}).then(refresh).catch(()=>{})
  }

  const openLesson=(lesson:any)=>{
    setSelectedLesson(lesson)
    setSheet('lesson')
  }
  const openSocialUser=(userId:number)=>{setSelectedSocialUser(userId);setSheet('social_profile')}
  const openMentionedInstrument=(instrumentId:number)=>{const item=instruments.find(instrument=>instrument.id===instrumentId);if(item){setSelected(item);setSheet('instrument')}}
  const openShareTrade=(trade:any)=>{setSelectedShareTrade(trade);setSheet('share_trade')}

  if(loading)return <div className="splash"><AlfaMark/><TinCharacter/><strong>Твои первые инвестиции<br/>без первого риска</strong><span>Готовим рынок…</span></div>
  const finishOnboarding=async()=>{setShowOnboarding(false);try{await api('/onboarding/complete',{method:'POST',body:JSON.stringify({shop_item_id:4})});refresh()}catch{} }
  const userCoins = Number(dashboard.wallet?.alfa_coins||0)
  const socialLabel = dashboard.user?.social_title || 'Тин-Ток'

  return <div className="app-shell">
    <aside className="desktop-side"><AlfaMark/><Nav page={page} setPage={navigatePage} socialLabel={socialLabel}/><small>Игровой симулятор<br/>Не инвестиционная рекомендация</small></aside>
    <div className="phone-shell">
      {error&&<ErrorBanner text={error} onClose={()=>setError('')}/>}
      <AnimatePresence mode="wait">
        {page==='home'&&<HomePage key="home" dashboard={dashboard} open={open} setPage={navigatePage} startMarketMission={startMarketMission} missionDone={marketMissionDone} openQuests={openQuests}/>} 
        {page==='market'&&<MarketPage key="market" instruments={instruments} select={select} openPiggy={()=>open('piggy')} streakState={dashboard.streak_state} onStreakClick={()=>open('streak')} missionTargetId={marketMissionTarget}/>} 
        {page==='tin'&&<TinPage key="tin" pet={pet} coins={userCoins} refresh={refresh} notify={notify} streakState={dashboard.streak_state} onStreakClick={()=>open('streak')}/>} 
        {page==='learn'&&<LearnPage key="learn" lessons={lessons} quests={quests} user={dashboard.user} refresh={refresh} notify={notify} streakState={dashboard.streak_state} onStreakClick={()=>open('streak')} onSelectLesson={openLesson} initialMode={learnInitialMode}/>} 
        {page==='social'&&<SocialPage key="social" fallbackTitle={socialLabel} streakState={dashboard.streak_state} onStreakClick={()=>open('streak')} onOpenUser={openSocialUser} onOpenInstrument={openMentionedInstrument} version={socialVersion} notify={notify}/>} 
        {page==='profile'&&<ProfilePage key="profile" dashboard={dashboard} achievements={achievements} open={open} onStreakClick={()=>open('streak')} onLogout={onLogout}/>} 
      </AnimatePresence>
      <Nav page={page} setPage={navigatePage} socialLabel={socialLabel}/>
    </div>
    <AnimatePresence>
      {showOnboarding&&<Onboarding finish={finishOnboarding}/>} 
      {sheet==='portfolio'&&<PortfolioSheet data={portfolio} allTimeChangePct={dashboard.all_time_change_pct} onClose={close} onShare={openShareTrade}/>} 
      {sheet==='convert'&&<ConvertSheet conversion={conversion} onClose={close} done={notify} refresh={refresh}/>} 
      {sheet==='shop'&&<ShopSheet items={items} coins={userCoins} goalId={dashboard.goal?.id} onClose={close} refresh={refresh} done={notify}/>} 
      {sheet==='instrument'&&selected&&<InstrumentSheet instrument={selected} onClose={close} refresh={refresh} done={notify} onShare={openShareTrade}/>} 
      {sheet==='piggy'&&<PiggySheet data={piggy} onClose={close} refresh={refresh} done={notify}/>} 
      {sheet==='news'&&<PortfolioNewsSheet onClose={close}/>} 
      {sheet==='contest'&&<ContestSheet data={contest} onClose={close} refresh={refresh} done={notify}/>} 
      {sheet==='referral'&&<ReferralSheet onClose={close} done={notify}/>}
      {sheet==='streak'&&dashboard.streak_state&&<StreakSheet streakState={dashboard.streak_state} onClose={close} done={notify} refresh={refresh}/>} 
      {sheet==='lesson'&&selectedLesson&&<LessonSheet lesson={selectedLesson} onClose={close} refresh={refresh} done={notify}/>} 
      {sheet==='edit_profile'&&<EditProfileSheet user={dashboard.user} onClose={close} refresh={refresh} done={notify}/>} 
      {sheet==='security'&&<SecuritySheet user={dashboard.user} onClose={close} done={notify}/>} 
      {sheet==='achievements'&&<AchievementsSheet items={achievements} onClose={close} refresh={refresh} done={notify}/>} 
      {sheet==='monthly_report'&&<MonthlyReportSheet onClose={close}/>} 
      {sheet==='social_profile'&&selectedSocialUser&&<SocialProfileSheet userId={selectedSocialUser} onClose={close} onChanged={()=>setSocialVersion(value=>value+1)} done={notify} onOpenInstrument={openMentionedInstrument}/>} 
      {sheet==='share_trade'&&selectedShareTrade&&<ShareTradeSheet trade={selectedShareTrade} onClose={close} onPublished={()=>setSocialVersion(value=>value+1)} done={notify}/>} 
    </AnimatePresence>
    <AnimatePresence>
      {toast&&<motion.div className="toast" initial={{y:30,opacity:0}} animate={{y:0,opacity:1}} exit={{opacity:0}}><Check size={18}/>{toast}</motion.div>}
    </AnimatePresence>
  </div>
}

export default function App(){
  const [token,setToken]=useState(getAccessToken)
  const [hostReady,setHostReady]=useState(!isEmbedded)
  const authenticated=useCallback((nextToken:string)=>{setAccessToken(nextToken);setToken(nextToken);emitPluginEvent('AUTHENTICATED')},[])
  const logout=useCallback(()=>{clearAccessToken();setToken('');emitPluginEvent('AUTH_REQUIRED',{reason:'signed_out'})},[])

  useEffect(()=>{
    if(!isEmbedded)return
    const onHostMessage=(event:MessageEvent)=>{
      if(!isTrustedHostMessage(event))return
      rememberHostOrigin(event.origin)
      const payload=event.data.payload||{}
      if(event.data.type==='HOST_INIT'){
        configureRuntime({
          apiBase:typeof payload.apiBase==='string'&&payload.apiBase?payload.apiBase:undefined,
          wsUrl:typeof payload.wsUrl==='string'&&payload.wsUrl?payload.wsUrl:undefined,
          theme:payload.theme==='dark'?'dark':'light',
          accessToken:typeof payload.accessToken==='string'?payload.accessToken:'',
        })
        const nextToken=typeof payload.accessToken==='string'?payload.accessToken:''
        setAccessToken(nextToken,false)
        setToken(nextToken)
        setHostReady(true)
        emitPluginEvent('PLUGIN_INITIALIZED',{authenticated:Boolean(nextToken)})
      }else if(event.data.type==='HOST_SET_TOKEN'){
        const nextToken=typeof payload.accessToken==='string'?payload.accessToken:''
        setAccessToken(nextToken,false)
        setToken(nextToken)
      }else if(event.data.type==='HOST_SET_THEME'&&(payload.theme==='light'||payload.theme==='dark')){
        applyHostTheme(payload.theme)
      }else if(event.data.type==='HOST_NAVIGATE'&&typeof payload.page==='string'){
        window.dispatchEvent(new CustomEvent('alfa-plugin-navigate',{detail:payload.page}))
      }else if(event.data.type==='HOST_REFRESH'){
        window.dispatchEvent(new Event('alfa-plugin-refresh'))
      }
    }
    window.addEventListener('message',onHostMessage)
    emitPluginEvent('PLUGIN_READY',{capabilities:['auth-token','theme','navigation','refresh'],protocolVersion:1})
    return()=>window.removeEventListener('message',onHostMessage)
  },[])

  useEffect(()=>{window.addEventListener('alfa-auth-expired',logout);return()=>window.removeEventListener('alfa-auth-expired',logout)},[logout])
  useEffect(()=>{if(isEmbedded&&hostReady&&!token)emitPluginEvent('AUTH_REQUIRED',{reason:'missing_token'})},[hostReady,token])
  if(!hostReady)return <div className="splash plugin-splash"><AlfaMark/><TinCharacter/><strong>Подключаем модуль…</strong><span>Получаем настройки Альфа‑Инвестиций</span></div>
  if(!token)return <AuthScreen onAuthenticated={authenticated}/>
  return <AuthenticatedApp key={token} onLogout={logout}/>
}
