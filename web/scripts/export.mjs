import {cp, mkdir, rm} from 'node:fs/promises';
await mkdir('../viewer/command', {recursive:true});
await rm('../viewer/command/_next', {recursive:true,force:true});
await cp('out', '../viewer/command', {recursive:true});
console.log('Command center exported to viewer/command');
