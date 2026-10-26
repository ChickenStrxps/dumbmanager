'use strict';
// Native-rate microphone input -> 16 kHz signed PCM, batched into 100 ms packets.
class DumbPCM extends AudioWorkletProcessor {
  constructor(){super();this.phase=0;this.sum=0;this.count=0;this.position=0;this.packet=new Int16Array(1600);}
  process(inputs){
    const samples=inputs[0]?.[0];if(!samples)return true;
    for(const sample of samples){
      this.sum+=sample;this.count++;this.phase+=16000;
      if(this.phase>=sampleRate){
        this.phase-=sampleRate;const value=Math.max(-1,Math.min(1,this.sum/this.count));this.sum=0;this.count=0;
        this.packet[this.position++]=Math.round(value*(value<0?32768:32767));
        if(this.position===1600){this.port.postMessage(this.packet.buffer,[this.packet.buffer]);this.packet=new Int16Array(1600);this.position=0;}
      }
    }
    return true;
  }
}
registerProcessor('dumb-pcm',DumbPCM);
