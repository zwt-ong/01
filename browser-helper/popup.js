"use strict";
document.querySelector('#identifier').textContent=chrome.runtime.id;
async function status(){const data=await chrome.storage.local.get(['run','dailyEnabled']);document.querySelector('#status').textContent=data.run?.message||'尚未开始采集';document.querySelector('#daily').checked=!!data.dailyEnabled;}
for(const action of ['pair','run','open','resume','skip','stop'])document.querySelector('#'+action).addEventListener('click',async()=>{try{const result=await chrome.runtime.sendMessage({action,token:document.querySelector('#token').value.trim()});if(result.error)throw new Error(result.error);document.querySelector('#token').value='';await status();if(action==='pair')document.querySelector('#status').textContent='配对成功，可以开始一轮采集';}catch(error){document.querySelector('#status').textContent=error.message;}});
document.querySelector('#daily').addEventListener('change',async event=>{try{const result=await chrome.runtime.sendMessage({action:'daily',enabled:event.target.checked});if(result.error)throw new Error(result.error);await status();}catch(error){document.querySelector('#status').textContent=error.message;}});
chrome.storage.onChanged.addListener(()=>status());status();
