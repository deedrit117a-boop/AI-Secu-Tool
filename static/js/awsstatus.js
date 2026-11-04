// ---------- 사이드바 위쪽의 'AWS 자격인증' 표시 (작은 타원)
// 이 환경에서 쓰기로 기억해 둔 AWS 프로필로 로그인(자격증명)이 되어 있으면 주황 계열로, 아니면 바탕과 같은 색으로 보인다.
// 확인은 읽기 전용(sts get-caller-identity)이고 서버가 잠깐 기억해 두므로 AWS CLI 를 자주 부르지 않는다.
// 누르면 지금 상태를 다시 확인하고, 로그인이 필요하면 로그인 안내(사용자가 브라우저에서 직접 승인)를 연다.
const awsPill={st:null,busy:false,t0:0,
  draw(){const b=$('#awspill');if(!b)return;const s=this.st||{state:'no_env'};const on=s.state==='ok';
    const why={ok:`인증 중 — 프로필 ${s.profile||''}${s.account?' · 계정 '+s.account:''}`,login_needed:`인증 안 됨 — 로그인이 필요합니다 (프로필 ${s.profile||''}). 누르면 로그인 안내를 엽니다`,
      no_profile:'인증 안 됨 — 이 환경에서 쓸 AWS 프로필이 아직 없습니다 (메타 데이터의 AWS 에서 가져오기에서 선택)',no_cli:'인증 안 됨 — AWS CLI 가 없습니다',no_env:'환경을 선택하면 확인합니다',error:'확인하지 못했습니다: '+(s.message||'')}[s.state]||'';
    b.className='awspill'+(on?' on':'');b.title=why;b.setAttribute('aria-label','AWS 자격인증: '+(on?'인증 중':'인증 안 됨')+'. '+why);
    b.innerHTML=`<span class="dot" aria-hidden="true"></span>AWS 자격인증${this.busy?' …':''}`},
  async refresh(force){if(this.busy)return;const b=$('#awspill');if(!b)return;
    if(!S.envId){this.st={state:'no_env'};this.draw();return}
    if(!force&&this.st&&Date.now()-this.t0<60000&&this.envId===S.envId)return;
    this.busy=true;this.draw();
    try{this.st=await api('GET',`/api/aws/status?env_id=${encodeURIComponent(S.envId)}${force?'&force=1':''}`);this.envId=S.envId}
    catch(e){this.st={state:'error',message:e.message}}
    this.busy=false;this.t0=Date.now();this.draw()},
  async click(){await this.refresh(true);const s=this.st||{};
    if(s.state==='login_needed'){if(await awsLoginFlow(s.profile,s.message||'AWS 로그인이 필요합니다.'))await this.refresh(true)}
    else if(s.state==='ok')toast(`AWS 자격인증이 되어 있습니다 (프로필 ${s.profile})`);
    else if(s.state==='no_profile'||s.state==='no_cli'||s.state==='error')toast(s.message||'AWS 자격인증을 확인하지 못했습니다',true,7000)},
  init(){const b=$('#awspill');if(!b)return;b.onclick=()=>this.click();this.draw();this.refresh(true);
    setInterval(()=>this.refresh(false),5*60*1000);window.addEventListener('focus',()=>this.refresh(false));
    const se=selectEnv;selectEnv=async function(...a){const r=await se.apply(this,a);awsPill.refresh(false);return r}}};
