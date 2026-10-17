/* board.js —— 渲染引擎（自 templates/dt/dashboard.html v2 抽取，与看板同一套代码）
   页面需提供容器：#h-title #h-date #h-badge #app #prov-body，并先加载 ECharts。
   用法：WB.render(REAL_DATA)（复盘六模块） / WB.renderStock(STOCK_DATA)（个股六模块） */
/* ================= 基础 ================= */
const UP='#e5484d', DOWN='#2fb37c', WARN='#e2b341', ACCENT='#4c8dff',
      MUTED='#8b95a5', LINE='#2a323e', TEXT='#d8dee8';
const STAGE_COLOR={'冰点':MUTED,'启动':ACCENT,'发酵':UP,'高潮':WARN,'退潮':DOWN};
const FONT={fontFamily:'Microsoft YaHei,PingFang SC,sans-serif',fontSize:11,color:MUTED};
const AXIS={axisLine:{lineStyle:{color:LINE}},axisLabel:FONT,splitLine:{lineStyle:{color:'rgba(42,50,62,.5)'}}};
const grid={left:56,right:20,top:32,bottom:26};
const tooltip={trigger:'axis',backgroundColor:'#1b222c',borderColor:LINE,textStyle:{color:TEXT,fontSize:12}};

function toneClass(w){
  if(/退潮|低迷|深冬|冰点|跌|拦截|回避/.test(w))return 'down';
  if(/发酵|回暖|偏暖|涨|高潮|入池/.test(w))return 'up';
  if(/谨慎|降温|预警|备查|观察/.test(w))return 'warn';
  return 'cold';
}
function gradeClass(g){return g==='优'?'up':(g==='中'?'warn':'down');}
function esc(s){return String(s==null?'—':s);}
function card(k,v,s,tone){return `<div class="card"><div class="k">${esc(k)}</div>
  <div class="v ${tone||''}">${esc(v)}</div><div class="s">${esc(s||'')}</div></div>`;}
function chart(el){
  const host=document.getElementById(el);
  if(typeof echarts==='undefined'){ /* IDE 内置浏览器等环境可能拦截 CDN——降级为提示，不阻塞整页渲染 */
    host.innerHTML='<div style="color:var(--muted);font-size:12px;padding:24px 10px;text-align:center">图表组件未能加载（当前环境限制了外部脚本），关键数值见相邻表格与卡片。</div>';
    return {setOption(){},resize(){}};
  }
  return echarts.init(host,null,{renderer:'canvas'});
}
function h(tag,cls,html){return `<${tag} class="${cls||''}">${html||''}</${tag}>`;}
function sec(title,sub,inner){return `<section class="sec"><h2>${title}
  <span class="sub">${sub||''}</span></h2>${inner}</section>`;}
function tbl(cols,rows){return `<table><thead><tr>${cols.map(c=>`<th>${c}</th>`).join('')}</tr></thead>
  <tbody>${rows.map(r=>`<tr>${r.map(c=>`<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;}
function ma(arr,n){const out=[];let s=0;for(let i=0;i<arr.length;i++){s+=arr[i];
  if(i>=n)s-=arr[i-n];out.push(i>=n-1?+(s/n).toFixed(2):null);}return out;}

/* ================= 图表助手 ================= */
function mkIntraday(id,{times,price,vwap,prevClose}){
  chart(id).setOption({backgroundColor:'transparent',tooltip,grid,
    xAxis:{type:'category',data:times,...AXIS},yAxis:{scale:true,...AXIS},
    series:[{name:'价格',type:'line',data:price,showSymbol:false,lineStyle:{color:ACCENT,width:1.4}},
      {name:'均价线',type:'line',data:vwap,showSymbol:false,lineStyle:{color:WARN,width:1.2}},
      ...(prevClose?[{name:'昨收',type:'line',data:times.map(()=>prevClose),showSymbol:false,
        lineStyle:{type:'dashed',color:MUTED,width:1}}]:[])]});
}
function mkVolume(id,{times,up,down}){
  chart(id).setOption({backgroundColor:'transparent',tooltip,grid,legend:{textStyle:FONT,top:0},
    xAxis:{type:'category',data:times,...AXIS},yAxis:{...AXIS},
    series:[{name:'上行量',type:'bar',stack:'v',data:up,itemStyle:{color:UP}},
      {name:'下行量',type:'bar',stack:'v',data:down,itemStyle:{color:DOWN}}]});
}
function mkLine(id,{times,series,area}){
  chart(id).setOption({backgroundColor:'transparent',tooltip,grid,
    legend:series.length>1?{textStyle:FONT,top:0}:undefined,
    xAxis:{type:'category',data:times,...AXIS},yAxis:{scale:true,...AXIS},
    series:series.map(s=>({name:s.name,type:'line',data:s.data,showSymbol:false,connectNulls:true,
      lineStyle:{color:s.color||ACCENT,width:1.4},
      areaStyle:area?{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[
        {offset:0,color:(s.color||ACCENT)+'30'},{offset:1,color:'transparent'}]}}:undefined}))});
}
function mkBar(id,{cats,values,colors,unit,horizontal}){
  chart(id).setOption({backgroundColor:'transparent',
    tooltip:{trigger:'item',backgroundColor:'#1b222c',borderColor:LINE,
      textStyle:{color:TEXT,fontSize:12},formatter:p=>`${p.name}：${p.value}${unit||''}`},
    grid:horizontal?{left:96,right:40,top:8,bottom:26}:grid,
    xAxis:{type:horizontal?'value':'category',data:horizontal?undefined:cats,...AXIS},
    yAxis:{type:horizontal?'category':'value',data:horizontal?cats:undefined,...AXIS},
    series:[{type:'bar',data:(values||[]).map((v,i)=>({value:v,
      itemStyle:{color:(Array.isArray(colors)?colors[i]:colors)||ACCENT}})),
      barMaxWidth:24,label:{show:true,position:horizontal?'right':'top',...FONT,color:TEXT}}]});
}
function mkIdxTrend(id,{dates,close,amount}){
  chart(id).setOption({backgroundColor:'transparent',tooltip,legend:{textStyle:FONT,top:0},
    grid:[{left:56,right:56,top:30,bottom:26}],
    xAxis:{type:'category',data:dates,...AXIS},
    yAxis:[{scale:true,name:'点位',nameTextStyle:FONT,...AXIS},
           {scale:true,name:'成交额(亿)',nameTextStyle:FONT,splitLine:{show:false},...AXIS}],
    series:[{name:'收盘',type:'line',data:close,showSymbol:false,
              lineStyle:{color:ACCENT,width:1.5}},
            {name:'20日线',type:'line',data:ma(close,20),showSymbol:false,connectNulls:true,
              lineStyle:{color:WARN,width:1.2}},
            {name:'成交额',type:'bar',yAxisIndex:1,data:amount,
              itemStyle:{color:'rgba(139,149,165,.35)'}}]});
}
function mkCandle(id,{dates,ohlc,ma5,ma20}){
  chart(id).setOption({backgroundColor:'transparent',tooltip,
    grid:{left:50,right:12,top:20,bottom:22},
    xAxis:{type:'category',data:dates,...AXIS,axisLabel:{...FONT,formatter:v=>v.slice(5)}},
    yAxis:{scale:true,...AXIS,splitLine:{show:false}},
    series:[{type:'candlestick',data:ohlc,
      itemStyle:{color:UP,color0:DOWN,borderColor:UP,borderColor0:DOWN}},
      ...(ma5?[{name:'5日线',type:'line',data:ma5,showSymbol:false,connectNulls:true,
        lineStyle:{color:WARN,width:1}}]:[]),
      ...(ma20?[{name:'20日线',type:'line',data:ma20,showSymbol:false,connectNulls:true,
        lineStyle:{color:ACCENT,width:1}}]:[])]});
}
function renderStageStrip(container,cur,tip){
  const stages=['冰点','启动','发酵','高潮','退潮'];
  document.getElementById(container).innerHTML=`<div class="strip">`+stages.map(s=>{
    const c=STAGE_COLOR[s]||MUTED;
    return `<div class="seg ${s===cur?'on':''}" style="${s===cur?`color:${c};border-color:${c}`:''}">
      ${s}${s===cur?`<span class="tip">${esc(tip||'当前位置')}</span>`:''}</div>`;}).join('')+`</div>`;
}
function candCard(o,idx){
  const five=(o.five||[]).map(([k,g])=>`<span class="${gradeClass(g)}">${k} ${g}</span>`).join('');
  const mets=(o.metrics||[]).map(([k,v,t])=>`<tr><td style="color:var(--muted)">${esc(k)}</td>
    <td class="${t||''}" style="text-align:right">${esc(v)}</td></tr>`).join('');
  return `<div class="cand">
    <div class="cand-h"><div><b>${esc(o.name)}</b><span class="cd">${esc(o.code)}</span></div>
      <span class="badge ${toneClass(o.badge)}">${esc(o.badge)}</span></div>
    <div class="cand-sub">${esc(o.sector)} · 周期档：${esc(o.horizon||'标准 1-2 周')}</div>
    <div class="dots">${five}${o.score?`<span>→ <b>${esc(o.score)}</b></span>`:''}</div>
    <table style="margin-bottom:6px">${mets}</table>
    ${o.k?`<div class="ec" id="ck-${idx}"></div>`:''}
    <div class="act"><b>对策：</b>${esc(o.action)}</div>
    ${o.note?`<div class="act" style="border:none;padding-top:4px;color:var(--muted)">${esc(o.note)}</div>`:''}
  </div>`;
}

/* ================= 复盘看板渲染引擎（注入 REAL_DATA 即用） ================= */
function renderReview(D){
  document.getElementById('h-title').textContent=D.meta.title;
  document.getElementById('h-date').textContent=D.meta.date+(D.meta.asof?(' · 数据截至 '+D.meta.asof):'');
  const bd=document.getElementById('h-badge');bd.textContent=D.meta.tone.text;bd.className='badge '+toneClass(D.meta.tone.text);
  document.getElementById('prov-body').innerHTML=(D.provenance||[]).map(p=>`${esc(p[0])}←${esc(p[1])}`).join('；');
  const app=document.getElementById('app');let html='';let chartJobs=[];

  /* ① 市场温度 */
  const T=D.temp;
  html+=sec('市场温度','环境层 × 博弈层 → 组合基调',
    `<div class="cards">${T.cards.map(c=>card(...c)).join('')}</div>
     <div id="strip-1"></div>
     <div class="note ${toneClass(D.meta.tone.text)}">${esc(T.combo.text)}<br>
       <span style="color:var(--muted)">${esc(T.combo.meaning)}</span></div>
     <div class="grid">
       <div class="chart span8"><h3>上证指数近 3 个月（收盘 / 20日线 / 成交额）</h3><div class="ec" id="ch-idx"></div></div>
       <div class="tbl span4"><h3>博弈层六指标</h3>${tbl(['指标','数值','口径'],T.l2table)}</div>
     </div>`);
  chartJobs.push(()=>{renderStageStrip('strip-1',T.stageStrip.current,T.stageStrip.tip);
    mkIdxTrend('ch-idx',T.idx);});

  /* ② 板块氛围 */
  const S=D.sectors;
  html+=sec('板块氛围','涨停家数 × 环节着色（蓝=启动 红=发酵 黄=高潮 绿=退潮）',
    `<div class="grid">
       <div class="chart span5"><h3>板块涨停家数（按环节着色）</h3><div class="ec" id="ch-sec"></div></div>
       <div class="tbl span7"><h3>板块地图</h3>${tbl(['板块','家数','梯队/龙头','催化','环节','分级'],S.table)}</div>
     </div>`);
  chartJobs.push(()=>mkBar('ch-sec',{cats:S.bars.names,values:S.bars.values,
    colors:S.bars.colors,unit:' 家',horizontal:true}));

  /* ③ 主线判定 */
  const M=D.mainline;
  html+=sec('主线判定','入池门槛四条件（板块是选股的主语）',
    `<div class="tbl" style="margin-bottom:10px">${tbl(['门槛条件','数据/证据','通过?'],M.gate)}</div>
     <div class="note ${toneClass(M.conclusion)}">${esc(M.conclusion)}<br>
       <span style="color:var(--muted)">${esc(M.leaders||'')}</span></div>`);

  /* ④ 推荐标的 */
  const cardsHtml=(D.cands||[]).map((c,i)=>candCard(c,i)).join('')||
    '<div class="note down">本日无推荐标的（原因见结论卡）</div>';
  html+=sec('推荐标的','每张卡：五维 + 指标参考组数值 + 迷你K线 + 对策',
    (D.candNote?`<div class="note warn">${esc(D.candNote)}</div>`:'')+`<div class="cands">${cardsHtml}</div>`);
  (D.cands||[]).forEach((c,i)=>{if(c.k)chartJobs.push(()=>mkCandle('ck-'+i,c.k));});

  /* ⑤ 自选滚动与持仓对策 */
  const W=D.watch;
  html+=sec('自选滚动与持仓对策','标准票>10日无进展移出；主线票放宽20日；板块退潮即移出',
    `<div class="note">${esc(W.roll)}</div>
     <div class="tbl" style="margin-bottom:10px"><h3>存量复查</h3>${tbl(W.cols,W.rows)}</div>
     <div class="tbl"><h3>持仓对策（分档）</h3>${tbl(['持仓','档','明日对策（条件化）'],W.holding)}</div>`);

  /* ⑥ 昨日台账验证 */
  const L=D.ledger;
  html+=sec('昨日预判验证','台账对账——判涨实涨/判涨实跌/判跌实涨（认错）/判跌实跌',
    `<div class="tbl">${tbl(['登记日','标的','方向','判断摘要','验证日','状态'],L.rows)}</div>`);

  app.innerHTML=html;
  chartJobs.forEach(f=>{try{f();}catch(e){}});
  window.addEventListener('resize',()=>{clearTimeout(window.__rsT);
    window.__rsT=setTimeout(()=>{chartJobs.forEach(f=>{try{f();}catch(e){}});},200);});
}

/* ================= 个股看板渲染（REAL_DATA.meta.type==='stock' 时走此引擎） ================= */
function renderStock(S){
  document.getElementById('h-title').textContent=S.meta.title;
  document.getElementById('h-date').textContent=S.meta.date+(S.meta.asof?(' · 数据截至 '+S.meta.asof):'');
  const bd=document.getElementById('h-badge');bd.textContent=S.meta.tone.text;bd.className='badge '+toneClass(S.meta.tone.text);
  document.getElementById('prov-body').innerHTML=(S.provenance||[]).map(p=>`${esc(p[0])}←${esc(p[1])}`).join('；');
  const app=document.getElementById('app');let html='';const jobs=[];

  /* ① 结论 */
  html+=sec('结论','评级 · 现价 · 资金 · 环境',
    `<div class="cards">${S.verdict.cards.map(c=>card(...c)).join('')}</div>
     <div class="note">${esc(S.verdict.oneLiner)}</div>
     <div class="note warn"><b>对策：</b>${esc(S.verdict.action)}</div>`);

  /* ② 前次判断对账 */
  html+=sec('前次判断对账','同票再次分析必含本节——台账逐条对照，禁止跳过',
    `<div class="tbl" style="margin-bottom:8px">${tbl(S.recon.cols,S.recon.rows)}</div>
     <div class="note">${esc(S.recon.note)}</div>`);

  /* ③ 分时承接力 */
  html+=sec('分时承接力','指标实测值（均价线/乖离/上行量/量比/脉冲），图表与读数同源、禁止读图替代',
    `<div class="grid">
       <div class="chart span6"><h3>分时价格与均价线（虚线=昨收）</h3><div class="ec" id="st-ip"></div></div>
       <div class="chart span6"><h3>上行/下行量分解（万元/5分钟）</h3><div class="ec" id="st-uv"></div></div>
     </div>
     <div class="grid" style="margin-top:10px">
       <div class="tbl span6"><h3>指标读数</h3>${tbl(['指标','数值','判读'],S.intraday.metrics)}</div>
       <div class="tbl span6"><h3>脉冲回撤测试</h3>${tbl(['时间','成交额','5根内回落','判定'],S.intraday.pulses)}</div>
     </div>`);
  jobs.push(()=>{mkIntraday('st-ip',S.intraday.line);mkVolume('st-uv',S.intraday.uv);});

  /* ④ 日线位置 */
  html+=sec('日线位置','近 40 个交易日 · 5/20 日均线',
    `<div class="grid">
       <div class="chart span7"><h3>日K与均线</h3><div class="ec" id="st-dk"></div></div>
       <div class="tbl span5"><h3>位置读数</h3>${tbl(['项','数值','说明'],S.daily.pos)}</div>
     </div>`);
  jobs.push(()=>mkCandle('st-dk',S.daily.k));

  /* ⑤ 情绪与板块环境 */
  html+=sec('情绪与板块环境','引用当日复盘已落盘数据，不重算',
    `<div class="cards">${S.context.cards.map(c=>card(...c)).join('')}</div>`);

  /* ⑥ 对策与预案 */
  html+=sec('对策与预案','介入/失效/兑现/持有分档——全部条件化可验证',
    `<div class="tbl" style="margin-bottom:8px">${tbl(['场景','条件 → 动作'],S.plan.rows)}</div>
     <div class="note">${esc(S.plan.ledger)}</div>`);

  app.innerHTML=html;
  jobs.forEach(f=>{try{f();}catch(e){}});
  window.addEventListener('resize',()=>{clearTimeout(window.__rsT);
    window.__rsT=setTimeout(()=>{jobs.forEach(f=>{try{f();}catch(e){}});},200);});
}


window.WB = {render: renderReview, renderStock: renderStock,
             card: card, mkIdxTrend: mkIdxTrend, mkBar: mkBar, mkCandle: mkCandle,
             mkLine: mkLine, renderStageStrip: renderStageStrip, toneClass: toneClass,
             tbl: tbl, sec: sec, ma: ma, candCard: candCard};
