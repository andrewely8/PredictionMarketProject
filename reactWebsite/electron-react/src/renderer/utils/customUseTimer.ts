// This is code taken from https://github.com/amrlabib/react-timer-hook
// most of the code in this file is not used. This file should be 
// made much simpler.
import { useState, useCallback, useEffect, useRef } from 'react';

const SECOND_INTERVAL = 1000;

export type TimeFromMillisecondsType = {
  totalMilliseconds: number,
  totalSeconds: number,
  milliseconds: number,
  seconds: number,
  minutes: number,
  hours: number,
  days: number,
};

export type AMPMType = '' | 'pm' | 'am';

export type FormattedTimeFromMillisecondsType = {
  milliseconds: number,
  seconds: number,
  minutes: number,
  hours: number,
  ampm?: AMPMType,
};


class Time {
  static getTimeFromMilliseconds(millisecs: number, isCountDown = true): TimeFromMillisecondsType {
    const totalSeconds = isCountDown ? Math.ceil(millisecs / 1000) : Math.floor(millisecs / 1000);
    const days = Math.floor(totalSeconds / (60 * 60 * 24));
    const hours = Math.floor((totalSeconds % (60 * 60 * 24)) / (60 * 60));
    const minutes = Math.floor((totalSeconds % (60 * 60)) / 60);
    const seconds = Math.floor(totalSeconds % 60);
    const milliseconds = Math.floor(millisecs % 1000);

    return {
      totalMilliseconds: millisecs,
      totalSeconds,
      milliseconds,
      seconds,
      minutes,
      hours,
      days,
    };
  }

  static getMillisecondsFromExpiry(expiry: Date): number {
    const now = new Date().getTime();
    const milliSecondsDistance = expiry?.getTime() - now;
    return milliSecondsDistance > 0 ? milliSecondsDistance : 0;
  }

  static getMillisecondsFromPrevTime(prevTime: number): number {
    const now = new Date().getTime();
    const milliSecondsDistance = now - prevTime;
    return milliSecondsDistance > 0 ? milliSecondsDistance : 0;
  }

  static getMillisecondsFromTimeNow(): number {
    const now = new Date();
    const currentTimestamp = now.getTime();
    const offset = (now.getTimezoneOffset() * 60 * 1000);
    return currentTimestamp - offset;
  }

  static getFormattedTimeFromMilliseconds(milliseconds: number, format?: '12-hour'): FormattedTimeFromMillisecondsType {
    const {
      milliseconds: millisecVal,
      seconds: secondsValue,
      minutes,
      hours,
    } = Time.getTimeFromMilliseconds(milliseconds);
    let ampm: AMPMType = '';
    let hoursValue = hours;

    if (format === '12-hour') {
      ampm = hours >= 12 ? 'pm' : 'am';
      hoursValue = hours % 12;
    }

    return {
      milliseconds: millisecVal,
      seconds: secondsValue,
      minutes,
      hours: hoursValue,
      ampm, 
    };
  }
}





function useInterval(callback: () => void, delay: number | null) {
  const callbackRef = useRef(callback);

  // update callback function with current render callback that has access to latest props and state
  useEffect(() => {
    callbackRef.current = callback;
  });

  useEffect(() => {
    if (!delay) {
      return () => {};
    }

    const interval = setInterval(() => {
      callbackRef?.current?.();
    }, delay);
    return () => clearInterval(interval);
  }, [delay]);
}




export type useStopwatchSettingsType = {
  autoStart?: boolean,
  offsetTimestamp?: Date,
  interval?: number,
};

export type useStopwatchResultType = TimeFromMillisecondsType & {
  start: () => void, 
  pause: () => void, 
  setPlaybackSpeed: (speed?: number) => void,
  reset: (offset?: Date, newAutoStart?: boolean) => void, 
  isRunning: boolean,
};

export function useStopwatch({ autoStart = false, offsetTimestamp, interval: customInterval = SECOND_INTERVAL}: useStopwatchSettingsType = {}): useStopwatchResultType {
  const offsetMilliseconds = offsetTimestamp ? Time.getMillisecondsFromExpiry(offsetTimestamp) : 0;
  const [prevTime, setPrevTime] = useState<number>(new Date().getTime() - new Date(offsetMilliseconds).getTime());
  const [milliseconds, setMilliseconds] = useState(Time.getMillisecondsFromPrevTime(prevTime || 0));
  const [isRunning, setIsRunning] = useState(autoStart);
  const millisecondsInitialOffset = SECOND_INTERVAL - (milliseconds % SECOND_INTERVAL);
  const [interval, setInterval] = useState(customInterval < millisecondsInitialOffset ? customInterval : millisecondsInitialOffset);

  //ADDED
  const [dt, setDt] = useState(1);


  useInterval(() => {
    if (interval !== customInterval) {
      setInterval(customInterval);
    }

    const now = new Date().getTime();
    const realElapsed = now - prevTime;
    setMilliseconds(milliseconds + realElapsed * dt);
    setPrevTime(now);
  }, isRunning ? interval : null);

  const start = useCallback(() => {
    setPrevTime(new Date().getTime());
    setIsRunning(true);
  }, [milliseconds]);

  const pause = useCallback(() => {
    if (isRunning) {
      const now = new Date().getTime();
      const realElapsed = now - prevTime;

      setMilliseconds(milliseconds + realElapsed * dt);
      setPrevTime(now);
      setIsRunning(false);
    }
  }, [prevTime, isRunning]);

  const reset = useCallback((offset?: Date, newAutoStart = false) => {
    const newOffsetMilliseconds = offset ? Time.getMillisecondsFromExpiry(offset) : 0;
    const newPrevTime = new Date().getTime() - new Date(newOffsetMilliseconds).getTime();
    const newMilliseconds = Time.getMillisecondsFromPrevTime(newPrevTime);
    const millisecondsOffset = SECOND_INTERVAL - (newMilliseconds % SECOND_INTERVAL);
    setPrevTime(newPrevTime);
    setMilliseconds(newMilliseconds);
    setInterval(customInterval < millisecondsOffset ? customInterval : millisecondsOffset);
    setIsRunning(newAutoStart);
  }, [customInterval]);


  const setPlaybackSpeed = useCallback((speed? : number) => {
    const newPlaybackSpeed = speed;
    setDt(newPlaybackSpeed);
  }, [])

  return {
    ...Time.getTimeFromMilliseconds(milliseconds, false), start, pause, reset, isRunning, setPlaybackSpeed,
  };
}