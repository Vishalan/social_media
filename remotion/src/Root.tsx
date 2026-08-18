import React from 'react';
import {Composition, CalculateMetadataFunction} from 'remotion';
import {StatCard, StatCardProps} from './compositions/StatCard';
import {HeadlineBurst, HeadlineBurstProps} from './compositions/HeadlineBurst';
import {Mechanism, MechanismProps} from './compositions/Mechanism';
import {SplitScreen, SplitScreenProps} from './compositions/SplitScreen';
import {CodeWalkthrough, CodeWalkthroughProps} from './compositions/CodeWalkthrough';
import {CinematicChart, CinematicChartProps} from './compositions/CinematicChart';
import {QuoteCard, QuoteCardProps} from './compositions/QuoteCard';
import {Lockup, LockupProps} from './compositions/Lockup';
import {SourcePull, SourcePullProps} from './compositions/SourcePull';
import {CtaCard, CtaCardProps} from './compositions/CtaCard';

/**
 * Canvas and duration come from input props, not from these defaults.
 *
 * The pipeline renders into a 1080x998 content panel today and may render full
 * frame later; a composition that hardcoded either would have to be rewritten
 * for the other. calculateMetadata lets one component serve both.
 */
type Sized = {width?: number; height?: number; fps?: number; durationInSeconds?: number};

const sized: CalculateMetadataFunction<any> = ({props}) => {
  const fps = props.fps ?? 25;
  const seconds = props.durationInSeconds ?? 3;
  return {
    fps,
    width: props.width ?? 1080,
    height: props.height ?? 998,
    durationInFrames: Math.max(2, Math.round(seconds * fps)),
  };
};

const PALETTE = ['#0B0D11', '#FFFFFF', '#22D3EE'];
const common = {width: 1080, height: 998, fps: 25, durationInSeconds: 3, palette: PALETTE};

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="StatCard"
        component={StatCard as any}
        durationInFrames={75}
        fps={25}
        width={1080}
        height={998}
        calculateMetadata={sized}
        defaultProps={{...common, value: '10-15x', support: 'larger open source codebase', kicker: 'codebase'} as any}
      />
      <Composition
        id="HeadlineBurst"
        component={HeadlineBurst as any}
        durationInFrames={75}
        fps={25}
        width={1080}
        height={998}
        calculateMetadata={sized}
        defaultProps={{...common, headline: 'Twitter always denied shadowbanning claims', accentFrom: 2} as any}
      />
      <Composition
        id="Mechanism"
        component={Mechanism as any}
        durationInFrames={112}
        fps={25}
        width={1080}
        height={998}
        calculateMetadata={sized}
        defaultProps={{
          ...common,
          durationInSeconds: 4.5,
          title: 'How the transparency tool works',
          steps: ['Post 10+ times in a month', 'Open Under the Hood settings', 'Download aggregate stats JSON'],
          result: 'See which labels hit your account',
        } as any}
      />
      <Composition
        id="SplitScreen"
        component={SplitScreen as any}
        durationInFrames={100}
        fps={25}
        width={1080}
        height={998}
        calculateMetadata={sized}
        defaultProps={{
          ...common,
          durationInSeconds: 4,
          kicker: 'what shipped',
          left: {label: 'Open sourced', value: 'For You ranking engine'},
          right: {label: 'Still closed', value: 'Grok spam filter'},
        } as any}
      />
      <Composition
        id="CodeWalkthrough"
        component={CodeWalkthrough as any}
        durationInFrames={100}
        fps={25}
        width={1080}
        height={998}
        calculateMetadata={sized}
        defaultProps={{
          ...common,
          durationInSeconds: 4,
          filename: 'the-algorithm/',
          lines: ['+ ranking/features.json', '+ ranking/eval-harness/', '- core/grok-integration/', '+ LICENSE (Apache-2.0)'],
          caption: 'What landed in the repo',
        } as any}
      />
      <Composition
        id="CinematicChart"
        component={CinematicChart as any}
        durationInFrames={100}
        fps={25}
        width={1080}
        height={998}
        calculateMetadata={sized}
        defaultProps={{
          ...common,
          durationInSeconds: 4,
          kicker: 'codebase size',
          bars: [
            {label: 'Before', value: 1, display: '1x'},
            {label: 'After', value: 13, display: '10-15x'},
          ],
        } as any}
      />
      <Composition
        id="QuoteCard"
        component={QuoteCard as any}
        durationInFrames={100}
        fps={25}
        width={1080}
        height={998}
        calculateMetadata={sized}
        defaultProps={{
          ...common,
          durationInSeconds: 4,
          quote: 'This is the kind of thing that I think people will be fairly shocked that we are releasing.',
          author: 'Keith Coleman',
          role: 'VP of Product, X',
        } as any}
      />
      <Composition
        id="Lockup"
        component={Lockup as any}
        durationInFrames={125}
        fps={25}
        width={1080}
        height={998}
        calculateMetadata={sized}
        defaultProps={{
          ...common,
          durationInSeconds: 5,
          title: 'Apache v2',
          badge: 'open source license',
          typed: 'The ranking engine code was released on GitHub under the Apache v2 license.',
        } as any}
      />
      <Composition
        id="SourcePull"
        component={SourcePull as any}
        durationInFrames={100}
        fps={25}
        width={1080}
        height={998}
        calculateMetadata={sized}
        defaultProps={{
          ...common,
          durationInSeconds: 4,
          sentence: 'X is significantly expanding its open source codebase, which includes the core ranking engine.',
          attribution: 'techcrunch.com',
          emphasis: 'core ranking engine',
        } as any}
      />
      <Composition
        id="CtaCard"
        component={CtaCard as any}
        durationInFrames={100}
        fps={25}
        width={1080}
        height={998}
        calculateMetadata={sized}
        defaultProps={{
          ...common,
          durationInSeconds: 4,
          kicker: 'want the link?',
          keyword: 'ALGORITHM',
          action: "Comment it and I'll send you the repo",
        } as any}
      />
    </>
  );
};
