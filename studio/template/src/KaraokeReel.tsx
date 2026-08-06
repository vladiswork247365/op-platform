import React from 'react';
import {
  AbsoluteFill, OffthreadVideo, Sequence, Audio,
  useCurrentFrame, useVideoConfig, spring, interpolate,
} from 'remotion';

type Word = {start: number; end: number; word: string};
// сильные слова — жёлтым (как в караоке-сабах)
const POWER = new Set(['СЕКРЕТ', 'ОШИБКА', 'ГЛАВНАЯ', 'ДЕНЬГИ', 'НИКТО', 'ПОЧЕМУ', 'ПРОДАЖ']);

export const KaraokeReel: React.FC<{videoSrc: string; music?: string; words: Word[]}> = ({
  videoSrc, music, words,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / fps;
  const active = words.find((w) => t >= w.start && t < w.end);
  return (
    <AbsoluteFill style={{backgroundColor: '#09090B'}}>
      {/* OffthreadVideo ОБЯЗАТЕЛЬНО в Sequence — иначе застывает на последнем кадре */}
      {videoSrc ? (
        <Sequence>
          <OffthreadVideo src={videoSrc} style={{width: '100%', height: '100%', objectFit: 'cover'}} />
        </Sequence>
      ) : null}
      {music ? <Audio src={music} volume={0.25} /> : null}
      {active ? <Caption word={active} /> : null}
    </AbsoluteFill>
  );
};

const Caption: React.FC<{word: Word}> = ({word}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  // bounce-pop на появлении слова (пружина: damping 12, stiffness 200)
  const s = spring({frame: frame - Math.round(word.start * fps), fps, config: {damping: 12, stiffness: 200}});
  const scale = interpolate(s, [0, 1], [0.4, 1]);
  const color = POWER.has(word.word.toUpperCase()) ? '#FFE500' : '#F5F5FA';
  return (
    <AbsoluteFill style={{justifyContent: 'flex-end', alignItems: 'center', paddingBottom: '34%'}}>
      <div
        style={{
          transform: `scale(${scale})`,
          fontFamily: 'Montserrat, sans-serif', fontWeight: 800, fontSize: 112,
          color, WebkitTextStroke: '7px #000', paintOrder: 'stroke fill',
          textTransform: 'uppercase', letterSpacing: '-1px',
        }}
      >
        {word.word}
      </div>
    </AbsoluteFill>
  );
};
