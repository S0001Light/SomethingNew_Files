from __future__ import annotations
import queue, threading, time, wave
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import numpy as np
import pygame
import pyaudiowpatch as pyaudio

W,H,FPS=1120,760,60
RATE,BLOCK=48000,256
BG=(12,16,25); PANEL=(24,31,44); BOX=(34,43,59); BORDER=(67,82,105)
TEXT=(240,244,250); MUTED=(154,166,185); BLUE=(69,159,255); GREEN=(52,211,132); YELLOW=(255,195,69); RED=(244,82,98)

def clamp(v,lo,hi): return max(lo,min(hi,v))
def stereo(a):
    if a.ndim==1: a=a[:,None]
    if a.shape[1]==1: return np.repeat(a,2,axis=1)
    return a[:,:2]
def soft_limit(x): return np.tanh(x*1.15)/np.tanh(1.15)
def pcm24(x):
    x=np.clip(x,-1.0,.9999999); n=(x*8388607).astype(np.int32).reshape(-1)
    o=np.empty((n.size,3),dtype=np.uint8); o[:,0]=n&255; o[:,1]=(n>>8)&255; o[:,2]=(n>>16)&255
    return o.tobytes()

@dataclass
class Device:
    index:int; name:str; channels:int; rate:int; loopback:bool=False

class Audio:
    def __init__(self):
        self.pa=pyaudio.PyAudio(); self.inputs=[]; self.loops=[]; self.outputs=[]; self.scan()
        self.mi=self.li=self.oi=0; self.mic_gain=1.; self.music_gain=.85; self.monitor_gain=.7
        self.delay_ms=0; self.monitor=True; self.record_system=True; self.gate=.008
        self.running=False; self.stop_evt=threading.Event(); self.mq=queue.Queue(24); self.sq=queue.Queue(24); self.oq=queue.Queue(24)
        self.writer=None; self.threads=[]; self.last_file=None; self.started=0.; self.status='Ready'; self.error=''
        self.mic_level=self.sys_level=self.peak=0.; self.dropped=0
    def scan(self):
        self.inputs.clear(); self.loops.clear(); self.outputs.clear(); loopids=set()
        try:
            for d in self.pa.get_loopback_device_info_generator(): loopids.add(int(d['index']))
        except Exception: pass
        for i in range(self.pa.get_device_count()):
            d=self.pa.get_device_info_by_index(i); name=str(d.get('name',f'Device {i}')); ins=int(d.get('maxInputChannels',0)); outs=int(d.get('maxOutputChannels',0)); rate=int(float(d.get('defaultSampleRate',RATE)))
            loop=i in loopids or bool(d.get('isLoopbackDevice',False)) or 'loopback' in name.lower()
            if ins:
                z=Device(i,name,max(1,min(2,ins)),rate,loop); (self.loops if loop else self.inputs).append(z)
            if outs: self.outputs.append(Device(i,name,max(1,min(2,outs)),rate))
    def sel(self,a,i): return a[clamp(i,0,len(a)-1)] if a else None
    def put(self,q,x):
        try:q.put_nowait(x)
        except queue.Full:
            try:q.get_nowait()
            except queue.Empty:pass
            try:q.put_nowait(x)
            except queue.Full:self.dropped+=1
    def capture(self,d,q,mic):
        s=None
        try:
            s=self.pa.open(format=pyaudio.paFloat32,channels=d.channels,rate=RATE,input=True,input_device_index=d.index,frames_per_buffer=BLOCK)
            while not self.stop_evt.is_set():
                x=np.frombuffer(s.read(BLOCK,exception_on_overflow=False),dtype=np.float32).reshape(-1,d.channels); x=stereo(x).astype(np.float32,copy=False)
                lv=float(np.sqrt(np.mean(x*x)+1e-12)); self.mic_level=lv if mic else self.mic_level; self.sys_level=lv if not mic else self.sys_level; self.put(q,x.copy())
        except Exception as e:self.error=f'Audio input error: {e}'; self.stop_evt.set()
        finally:
            if s:
                try:s.stop_stream();s.close()
                except:pass
    def playback(self,d):
        s=None
        try:
            s=self.pa.open(format=pyaudio.paFloat32,channels=2,rate=RATE,output=True,output_device_index=d.index,frames_per_buffer=BLOCK)
            while not self.stop_evt.is_set():
                try:x=self.oq.get(timeout=.1)
                except queue.Empty:x=np.zeros((BLOCK,2),np.float32)
                s.write(x.astype(np.float32,copy=False).tobytes(),exception_on_underflow=False)
        except Exception as e:self.error=f'Monitor error: {e}'
        finally:
            if s:
                try:s.stop_stream();s.close()
                except:pass
    def mix(self):
        zero=np.zeros((BLOCK,2),np.float32); blocks=int(round(self.delay_ms*RATE/1000/BLOCK)); delay=deque([zero.copy() for _ in range(blocks)])
        while not self.stop_evt.is_set():
            try:mic=self.mq.get(timeout=.15)
            except queue.Empty:mic=zero.copy()
            try:system=self.sq.get_nowait() if self.record_system else zero.copy()
            except queue.Empty:system=zero.copy()
            if self.gate>0 and float(np.sqrt(np.mean(mic*mic)+1e-12))<self.gate: mic=mic*.12
            # RECORD PATH: microphone + computer output.
            rec=soft_limit(mic*self.mic_gain+system*self.music_gain); self.peak=max(self.peak*.94,float(np.max(np.abs(rec))))
            if self.writer:self.writer.writeframesraw(pcm24(rec))
            # MONITOR PATH: MICROPHONE ONLY. System/loopback never enters monitor output.
            mon=mic
            if blocks: delay.append(mic); mon=delay.popleft()
            if self.monitor:self.put(self.oq,soft_limit(mon*self.mic_gain*self.monitor_gain))
    def start(self):
        if self.running:return
        mic,loop,out=self.sel(self.inputs,self.mi),self.sel(self.loops,self.li),self.sel(self.outputs,self.oi)
        if not mic:self.error='No microphone found.';return
        if self.record_system and not loop:self.error='No WASAPI loopback found.';return
        if self.monitor and not out:self.error='No monitor output found.';return
        folder=Path.home()/'Music'/'WJKaraoke';folder.mkdir(parents=True,exist_ok=True);self.last_file=folder/f'karaoke_{datetime.now():%Y%m%d_%H%M%S}.wav'
        self.writer=wave.open(str(self.last_file),'wb');self.writer.setnchannels(2);self.writer.setsampwidth(3);self.writer.setframerate(RATE)
        self.error='';self.status='Recording';self.started=time.perf_counter();self.stop_evt.clear();self.running=True;self.peak=0.;self.dropped=0
        self.threads=[threading.Thread(target=self.capture,args=(mic,self.mq,True),daemon=True),threading.Thread(target=self.mix,daemon=True)]
        if self.record_system:self.threads.append(threading.Thread(target=self.capture,args=(loop,self.sq,False),daemon=True))
        if self.monitor:self.threads.append(threading.Thread(target=self.playback,args=(out,),daemon=True))
        for t in self.threads:t.start()
    def stop(self):
        if not self.running:return
        self.stop_evt.set()
        for t in self.threads:t.join(timeout=1.5)
        if self.writer:self.writer.close()
        self.writer=None;self.running=False;self.status='Saved'
        for q in (self.mq,self.sq,self.oq):
            while not q.empty():
                try:q.get_nowait()
                except queue.Empty:break
    def close(self):self.stop();self.pa.terminate()

class Button:
    def __init__(self,r,t,c=BLUE):self.r=pygame.Rect(r);self.t=t;self.c=c
    def draw(self,s,f,on=True):pygame.draw.rect(s,self.c if on else BORDER,self.r,border_radius=8);z=f.render(self.t,True,(10,15,23));s.blit(z,z.get_rect(center=self.r.center))
    def hit(self,p):return self.r.collidepoint(p)
class Slider:
    def __init__(self,r,lo,hi,v,label,fmt):self.r=pygame.Rect(r);self.lo=lo;self.hi=hi;self.v=v;self.label=label;self.fmt=fmt;self.drag=False
    def event(self,e):
        if e.type==pygame.MOUSEBUTTONDOWN and e.button==1 and self.r.inflate(0,22).collidepoint(e.pos):self.drag=True;self.set(e.pos[0]);return True
        if e.type==pygame.MOUSEMOTION and self.drag:self.set(e.pos[0]);return True
        if e.type==pygame.MOUSEBUTTONUP and e.button==1:self.drag=False
        return False
    def set(self,x):self.v=self.lo+clamp((x-self.r.x)/self.r.w,0,1)*(self.hi-self.lo)
    def draw(self,s,small):
        s.blit(small.render(f'{self.label}: {self.fmt.format(self.v)}',True,TEXT),(self.r.x,self.r.y-24));pygame.draw.rect(s,BORDER,self.r,border_radius=5);f=(self.v-self.lo)/(self.hi-self.lo);pygame.draw.rect(s,BLUE,(self.r.x,self.r.y,int(self.r.w*f),self.r.h),border_radius=5);pygame.draw.circle(s,TEXT,(self.r.x+int(self.r.w*f),self.r.centery),9)
class Box:
    def __init__(self,r,label):self.r=pygame.Rect(r);self.label=label
    def draw(self,s,f,small,a,i,on=True):
        s.blit(small.render(self.label,True,MUTED),(self.r.x,self.r.y-21));pygame.draw.rect(s,BOX if on else PANEL,self.r,border_radius=7);pygame.draw.rect(s,BORDER,self.r,1,border_radius=7);n=a[i].name if a else 'No device found';n=n if len(n)<=54 else n[:51]+'...';s.blit(f.render(n,True,TEXT if on else MUTED),(self.r.x+12,self.r.y+10));s.blit(f.render('<   >',True,BLUE if on else MUTED),(self.r.right-62,self.r.y+10))
    def click(self,p,a,i):return ((i-1)%len(a) if p[0]<self.r.centerx else (i+1)%len(a)) if a and self.r.collidepoint(p) else i
def meter(s,r,v,label,small):
    pygame.draw.rect(s,BOX,r,border_radius=5);x=clamp(v*5,0,1);pygame.draw.rect(s,GREEN if x<.72 else YELLOW if x<.9 else RED,(r.x,r.y,int(r.w*x),r.h),border_radius=5);s.blit(small.render(label,True,TEXT),(r.x,r.y-20))
def main():
    pygame.init();screen=pygame.display.set_mode((W,H));pygame.display.set_caption('WritersJumbler Karaoke Recorder');clock=pygame.time.Clock();title=pygame.font.SysFont('segoeui',29,bold=True);font=pygame.font.SysFont('segoeui',18);small=pygame.font.SysFont('segoeui',15);big=pygame.font.SysFont('consolas',36,bold=True);a=Audio()
    mb=Box((45,120,500,46),'MICROPHONE');lb=Box((575,120,500,46),'SYSTEM AUDIO (RECORD ONLY)');ob=Box((45,205,500,46),'MIC-ONLY MONITOR OUTPUT')
    delay=Slider((575,220,500,10),0,50,0,'Mic monitor delay','{:.0f} ms');mg=Slider((45,330,315,10),0,2,1,'Mic record/monitor gain','{:.2f}x');sg=Slider((403,330,315,10),0,2,.85,'System record gain','{:.2f}x');og=Slider((760,330,315,10),0,1.5,.7,'Mic monitor volume','{:.2f}x');gate=Slider((45,425,315,10),0,.04,.008,'Noise gate','{:.3f}');sl=[delay,mg,sg,og,gate]
    rec=Button((45,610,205,55),'START RECORDING',RED);stop=Button((265,610,130,55),'STOP',YELLOW);mon=Button((410,610,180,55),'MIC MONITOR: ON',GREEN);sysb=Button((605,610,210,55),'SYSTEM RECORD: ON');ref=Button((830,610,245,55),'REFRESH DEVICES')
    run=True
    while run:
        for e in pygame.event.get():
            if e.type==pygame.QUIT:run=False
            for z in sl:z.event(e)
            if e.type==pygame.MOUSEBUTTONDOWN and e.button==1:
                if not a.running:
                    a.mi=mb.click(e.pos,a.inputs,a.mi);a.li=lb.click(e.pos,a.loops,a.li);a.oi=ob.click(e.pos,a.outputs,a.oi)
                    if rec.hit(e.pos):a.start()
                    elif mon.hit(e.pos):a.monitor=not a.monitor;mon.t=f"MIC MONITOR: {'ON' if a.monitor else 'OFF'}"
                    elif sysb.hit(e.pos):a.record_system=not a.record_system;sysb.t=f"SYSTEM RECORD: {'ON' if a.record_system else 'OFF'}"
                    elif ref.hit(e.pos):a.scan();a.mi=a.li=a.oi=0;a.status='Devices refreshed'
                if stop.hit(e.pos):a.stop()
        if not a.running:a.delay_ms=int(round(delay.v));a.mic_gain=mg.v;a.music_gain=sg.v;a.monitor_gain=og.v;a.gate=gate.v
        screen.fill(BG);screen.blit(title.render('WritersJumbler Karaoke Recorder',True,TEXT),(45,30));screen.blit(small.render('Recording = microphone + computer sound   |   Monitoring = microphone ONLY',True,MUTED),(45,70));pygame.draw.rect(screen,PANEL,(25,95,1070,190),border_radius=12);mb.draw(screen,font,small,a.inputs,a.mi,not a.running);lb.draw(screen,font,small,a.loops,a.li,not a.running);ob.draw(screen,font,small,a.outputs,a.oi,not a.running);delay.draw(screen,small);pygame.draw.rect(screen,PANEL,(25,300,1070,190),border_radius=12)
        for z in sl[1:]:z.draw(screen,small)
        meter(screen,pygame.Rect(403,412,315,14),a.mic_level,'MIC LEVEL',small);meter(screen,pygame.Rect(760,412,315,14),a.sys_level,'SYSTEM RECORD LEVEL',small);pygame.draw.rect(screen,BOX,(25,510,1070,75),border_radius=12);et=time.perf_counter()-a.started if a.running else 0;tm=f'{int(et)//3600:02d}:{(int(et)//60)%60:02d}:{int(et)%60:02d}';screen.blit(big.render(tm,True,RED if a.running else TEXT),(45,526));screen.blit(font.render(a.error or a.status,True,RED if a.error else GREEN),(285,525));rec.draw(screen,font,not a.running);stop.draw(screen,font,a.running);mon.draw(screen,font,not a.running);sysb.draw(screen,font,not a.running);ref.draw(screen,font,not a.running);screen.blit(small.render('Loopback is captured for the WAV file but is never sent to the monitor output.',True,MUTED),(45,705));pygame.display.flip();clock.tick(FPS)
    a.close();pygame.quit()
if __name__=='__main__':main()
