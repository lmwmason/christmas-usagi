"""Beat-driven Usagi singing with independent source-vocal coverage auditing."""
from pathlib import Path
from collections import Counter, deque
import json
import math
import tempfile

import librosa
import numpy as np
import parselmouth
from parselmouth.praat import call
import soundfile as sf

from tools.build_preview import ROOT, SR, decode, extract_notes, fade, run
from tools.expressive import load_units, synthesize
from tools.vocal_activity import detect_vocals, coverage, envelope, HOP
from tools.source_policy import allowed_source


def natural_voice(unit, duration):
    factor=float(np.clip(duration/unit['duration'],.82,1.22))
    manipulation=call(unit['sound'],'To Manipulation',.01,100,1400)
    tier=call('Create DurationTier','length',0,unit['duration'])
    call(tier,'Add point',0,factor);call(tier,'Add point',unit['duration'],factor)
    call([tier,manipulation],'Replace duration tier')
    result=call(manipulation,'Get resynthesis (overlap-add)').values[0].astype(np.float32)
    return fade(result,.005),factor,0


def guide_for(notes,left,right):
    return [n for n in notes if n['time']<right and n['time']+n['duration']>left]


def render_preview(*,song,output,start=0,duration=30,sample_manifest=ROOT/'assets/sources/manifest.json',melody=None,keep_duration=True,source_url='https://www.youtube.com/watch?v=yXQViqx6GMY',notify=None,notes=None,rhythm=None,pitch_model=None):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='usagi-rap-') as directory:
        temp=Path(directory)
        original=decode(Path(song),temp/'original.wav',start,duration)
        lead=decode(Path(melody),temp/'lead.wav',0,duration) if melody else original
        seconds=min(len(original),len(lead))/SR
        reference,regions,activity=detect_vocals(lead,original,SR)
        if not regions:raise ValueError('노래 부르는 구간을 찾지 못했어요. 다른 곡이나 구간을 골라주세요.')
        units=load_units(sample_manifest,temp)
        if notify:notify(.1,'우사기 랩의 다양한 발성을 준비했어요')
        if notes is None:
            if notify:notify(.15,'보컬 구간과 멜로디를 따로 분석하고 있어요')
            progress=(lambda v,m:notify(.15+.25*v,m)) if notify else None
            if pitch_model:
                from tools.neural_pitch import extract_neural_notes
                notes=extract_neural_notes(lead,SR,pitch_model,notify=progress,allow_empty=True)
            else:
                notes=extract_notes(lead,notify=progress,allow_empty=True)
        notes=[dict(n) for n in notes if 'midi' in n and 0<=n['time']<seconds]
        singing=[u for u in units if u['voiced']>=.45 and u['spread']<9]
        if len(singing)<5:singing=units
        bpm=float((rhythm or {}).get('bpm') or 150)
        # Beat trackers often choose the half-time pulse of a fast pop song.
        while bpm<105:bpm*=2
        while bpm>195:bpm/=2
        quarter=60/bpm
        source_beats=np.array((rhythm or {}).get('beats',[]))
        grid=np.sort(np.concatenate([a+(b-a)*np.arange(4)/4 for a,b in zip(source_beats,source_beats[1:])])) if len(source_beats)>1 else np.arange(0,seconds,quarter/2)
        pattern=[1,1,2,.5,.5,1,2,1,1,4,1,2,.5,.5,2,1,3,1]
        canvas=np.zeros(len(original),dtype=np.float32)
        phrases=[];uses=Counter();recent=deque(maxlen=4);phrase_index=0

        def lay(unit,begin,voice,factor,shift,kind,guide,accent=1):
            first=max(0,round(begin*SR));size=min(len(voice),len(canvas)-first)
            if size<=0:return 0
            voice=fade(voice[:size],.005)
            level=float(np.sqrt(np.mean(voice**2)))
            voice*=float(np.clip(.135*accent/max(level,.008),.5,2.5))
            canvas[first:first+size]+=voice
            phrases.append(dict(time=first/SR,duration=size/SR,sampleId=unit['id'],name=unit['name'],kind=kind,timeFactor=round(factor,4),maxShiftSemitones=round(shift,3),sourceStart=unit['sourceStart'],sourceEnd=unit['sourceEnd']))
            uses[unit['id']]+=1;recent.append(unit['id'])
            return size/SR

        for region_index,(left,right) in enumerate(regions):
            cursor=left
            while cursor<right-.025:
                if notify:notify(.4+.42*cursor/max(seconds,.1),'보컬이 있는 모든 구간에 우사기 발성을 채우고 있어요')
                remaining=right-cursor
                desired=min(remaining,quarter*pattern[phrase_index%len(pattern)])
                guide=guide_for(notes,cursor,cursor+desired)
                pool=singing if guide else units
                # Use genuine utterances close to the slot length, rather than
                # compressing a long phrase to a few milliseconds.
                choices=[u for u in pool if u['duration']*.82<=remaining+.04]
                if not choices:choices=sorted(pool,key=lambda u:u['duration'])[:4]
                target=float(np.average([n['midi'] for n in guide],weights=[n['duration'] for n in guide])) if guide else None
                def score(u):
                    ratio=desired/u['duration']
                    return (abs(math.log2(max(ratio,.01)))*3
                            +(abs(u['midi']-target)*.14 if target is not None else u['spread']*.015)
                            +(1-u['voiced'])*.5+u['spread']*.02
                            +(.9 if recent and recent[-1]==u['id'] else .2*recent.count(u['id']))
                            +min(.5,math.log1p(uses[u['id']])*.08)
                            +(.18 if pattern[phrase_index%len(pattern)]>=2 and u['group']!='phrases' else 0))
                unit=min(choices,key=score)
                slot=min(remaining,float(np.clip(desired,unit['duration']*.82,unit['duration']*1.22)))
                guide=guide_for(notes,cursor,cursor+slot)
                if guide:
                    voice,factor,shift=synthesize(unit,guide,slot,begin=cursor)
                    kind='melody'
                else:
                    voice,factor,shift=natural_voice(unit,slot)
                    kind='rap'
                voice=voice[:max(1,round(remaining*SR))]
                used=lay(unit,cursor,voice,factor,shift,kind,guide,1.1 if phrase_index%4==0 else 1)
                next_cursor=cursor+max(.04,used-.018)
                if len(grid):
                    position=int(np.searchsorted(grid,next_cursor))
                    nearby=grid[max(0,position-1):position+1]
                    if len(nearby):
                        snapped=float(nearby[np.argmin(np.abs(nearby-next_cursor))])
                        if abs(snapped-next_cursor)<=.045 and snapped>cursor+.08 and snapped<right:next_cursor=snapped
                cursor=next_cursor
                phrase_index+=1

        # A longer source utterance can contain a silence in the middle. Fill
        # only those missed vocal frames, with a short actual voiced fragment.
        # This keeps the limited time warp while covering held sung vowels.
        repair_units=[u for u in singing if u['voiced']>.65 and u['duration']>.18]
        for pass_index in range(3):
            stats,gaps=coverage(canvas,reference,SR)
            gaps=[(a,min(b,seconds)) for a,b in gaps if b-a>.065]
            if not gaps:break
            for left,right in gaps:
                cursor=max(0,left-.012)
                while cursor<right-.02:
                    target_length=min(.24,right-cursor+.01)
                    parent=min(repair_units or singing,key=lambda u:(uses[u['id']]*.01+u['spread']*.05+abs(u['duration']-.35)))
                    samples=min(len(parent['raw']),max(round(.09*SR),round(target_length*SR)))
                    cumulative=np.r_[0,np.cumsum(parent['raw'].astype(np.float64)**2)]
                    power=(cumulative[samples:]-cumulative[:-samples])/samples
                    offset=int(np.argmax(power)) if len(power) else 0
                    raw=parent['raw'][offset:offset+samples].copy()
                    sound=parselmouth.Sound(raw,sampling_frequency=SR)
                    pitch=sound.to_pitch_ac(time_step=.01,pitch_floor=100,pitch_ceiling=1400)
                    freq=pitch.selected_array['frequency'];freq=freq[freq>0]
                    if not len(freq):break
                    fragment=dict(parent,raw=raw,sound=sound,pitch=pitch,duration=len(raw)/SR,midi=float(np.median(librosa.hz_to_midi(freq))),sourceStart=parent['sourceStart']+offset/SR,sourceEnd=parent['sourceStart']+(offset+len(raw))/SR)
                    guide=guide_for(notes,cursor,cursor+target_length)
                    voice,factor,shift=synthesize(fragment,guide,target_length,begin=cursor) if guide else natural_voice(fragment,target_length)
                    voice=voice[:max(1,round((right-cursor+.012)*SR))]
                    used=lay(fragment,cursor,voice,factor,shift,'sustain',guide)
                    cursor+=max(.04,used-.008)
            if notify:notify(.84+.025*pass_index,'노래 구간이 비지 않았는지 확인하고 있어요')
        audit,_=coverage(canvas,reference,SR)
        if audit['ratio']<.98 or audit['maxGapSeconds']>.14:
            raise ValueError('일부 보컬 구간을 충분히 채우지 못했어요. 더 짧은 구간으로 다시 시도해 주세요.')

        # Beat-aligned, intact responses in instrumental rests. They do not
        # substitute for the continuous singing above.
        pauses=[(a[1],b[0]) for a,b in zip(regions,regions[1:]) if b[0]-a[1]>.9]
        beats=np.array((rhythm or {}).get('beats',[]))
        for index,(left,right) in enumerate(pauses):
            if index%2:continue
            candidates=[u for u in units if .2<u['duration']<min(1.5,right-left-.15)]
            if not candidates:continue
            unit=min(candidates,key=lambda u:recent.count(u['id'])*.5+uses[u['id']]*.015+abs(u['duration']-.6))
            possible=beats[(beats>left+.03)&(beats<right-unit['duration']-.03)]
            at=float(possible[0]) if len(possible) else left+.08
            lay(unit,at,unit['raw'].copy(),1,0,'adlib',[],1.05)
        delay=round(.055*SR);canvas[delay:]+=canvas[:-delay].copy()*.05
        peak=float(np.max(np.abs(canvas)));canvas*=min(1,.88/max(peak,.001))
        final_audit,_=coverage(canvas,reference,SR)
        sf.write(temp/'voice.wav',fade(canvas,.02),SR)
        run('ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(temp/'voice.wav'),'-codec:a','libmp3lame','-b:a','160k',str(output/'usagi-vocals.mp3'))
        phrases.sort(key=lambda p:p['time'])
        events=[dict(time=p['time'],duration=p['duration'],sampleId=p['sampleId'],kind=p['kind']) for p in phrases]
        metadata=dict(method='Beat-driven pitch-synchronous Usagi rap singing',status='experimental; listening review required',sourceBank='assets/sources/manifest.json',songSource=source_url,songStart=start,duration=len(canvas)/SR,bankSize=len(json.loads(Path(sample_manifest).read_text())),usedSounds=dict(uses),phrases=phrases,notes=events,melodyNotes=notes,vocalRegions=[dict(time=a,duration=b-a) for a,b in regions],vocalCoverage=final_audit,vocalActivity=activity,arrangement=dict(style='energetic-rap',quarterBpm=bpm,phraseCount=len(phrases)),qualityBounds=dict(timeFactor=[.82,1.22],maxShiftSemitones=6,octaveTranspose=0))
        if rhythm:metadata['rhythm']=rhythm
        metadata['sourcePolicyVersion']=1
        metadata['bankSize']=sum(allowed_source(item) for item in json.loads(Path(sample_manifest).read_text()))
        metadata['pitchAnalysis']='RMVPE ONNX CPU' if pitch_model else 'pYIN CPU'
        (output/'preview.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
        if notify:notify(1,'보컬 구간을 채운 우사기 공연을 마쳤어요')
        return metadata
