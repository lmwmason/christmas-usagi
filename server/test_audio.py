"""Checks for missing sung passages, including consonants without stable F0."""
import unittest
import numpy as np

from tools.vocal_activity import detect_vocals,coverage,HOP
from tools.build_preview import extract_notes
from tools.source_policy import allowed_source
from tools.neural_pitch import decode_salience


class SourcePolicyTests(unittest.TestCase):
    def test_reported_dialogue_is_blocked_by_id_and_content(self):
        import json
        from tools.source_policy import POLICY
        bad=json.loads(POLICY.read_text())['blocked'][0]
        self.assertFalse(allowed_source({'id':bad['id']}))
        self.assertFalse(allowed_source({'id':'renamed-copy','sha256':bad['sha256']}))
        self.assertTrue(allowed_source({'id':'wula-70712','sha256':'different'}))

    def test_rmvpe_pitch_bins_and_silence(self):
        salience=np.zeros((2,360),dtype=np.float32)
        # 440 Hz maps to ~6551 cents relative to 10 Hz.
        cents=1200*np.log2(440/10)
        index=round((cents-1997.3794084376191)/20)
        salience[0,index]=1
        f0=decode_salience(salience)
        self.assertLess(abs(12*np.log2(f0[0]/440)),.11)
        self.assertEqual(f0[1],0)

SR=22050


class VocalCoverageTests(unittest.TestCase):
    def setUp(self):
        self.t=np.arange(6*SR)/SR
        self.voice=np.zeros(len(self.t),dtype=np.float32)
        self.voice[SR:3*SR]=.12*np.sin(2*np.pi*330*self.t[SR:3*SR])
        # A noisy consonant is speech even though it has no measurable note.
        noise=np.random.default_rng(4).normal(0,.06,round(.25*SR)).astype(np.float32)
        self.voice[round(1.7*SR):round(1.7*SR)+len(noise)]=noise
        self.voice[4*SR:5*SR]=.1*np.sin(2*np.pi*440*self.t[4*SR:5*SR])
        self.mix=self.voice+.07*np.sin(2*np.pi*196*self.t)
        self.mask,self.regions,_=detect_vocals(self.voice,self.mix,SR)

    def test_unpitched_consonants_are_not_dropped(self):
        first=round(1.75*SR/HOP);last=round(1.9*SR/HOP)
        self.assertTrue(np.all(self.mask[first:last]))
        self.assertFalse(np.any(self.mask[:round(.5*SR/HOP)]))

    def test_long_missing_sung_passage_fails_coverage(self):
        broken=self.voice.copy();broken[round(1.3*SR):round(2.2*SR)]=0
        audit,gaps=coverage(broken,self.mask,SR)
        self.assertLess(audit['ratio'],.85)
        self.assertGreater(audit['maxGapSeconds'],.7)

    def test_complete_voice_passes_with_articulation_tolerance(self):
        audit,_=coverage(self.voice,self.mask,SR)
        self.assertGreater(audit['ratio'],.98)
        self.assertLess(audit['maxGapSeconds'],.06)

    def test_instrumental_leak_is_not_a_singer(self):
        instrumental=.1*np.sin(2*np.pi*196*self.t)
        mask,_,_=detect_vocals(instrumental*.02,instrumental,SR)
        self.assertFalse(np.any(mask))

    def test_sustained_notes_are_kept_without_breaking_analysis(self):
        tone=(.12*np.sin(2*np.pi*440*np.arange(round(1.5*SR))/SR)).astype(np.float32)
        notes=extract_notes(tone)
        self.assertGreater(sum(n['duration'] for n in notes),1)
        self.assertTrue(all(abs(n['midi']-69)<=1 for n in notes))


if __name__=='__main__':unittest.main()
