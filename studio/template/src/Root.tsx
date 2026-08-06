import React from 'react';
import {Composition} from 'remotion';
import {KaraokeReel} from './KaraokeReel';

// Каждая композиция = стиль (движок). Здесь — караоке-сабы поверх видео (podcast-cuts).
export const RemotionRoot: React.FC = () => (
  <Composition
    id="KaraokeReel"
    component={KaraokeReel}
    durationInFrames={30 * 20}
    fps={30}
    width={1080}
    height={1920}
    defaultProps={{
      videoSrc: '',
      music: '',
      words: [
        {start: 0.0, end: 0.5, word: 'ГЛАВНАЯ'},
        {start: 0.5, end: 1.1, word: 'ОШИБКА'},
        {start: 1.1, end: 1.7, word: 'ПРОДАЖ'},
      ],
    }}
  />
);
