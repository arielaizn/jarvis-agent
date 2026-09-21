import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.180.0/build/three.module.js';

const GROUP_COLORS = ['#93ead0', '#8cbdff', '#d3a1ff', '#f1bc85', '#e594ba', '#b8d899', '#89d9e5', '#e1d395'];
const IDLE_ROTATION_SPEED = 0.28;
const FLY_DURATION_MS = 1200;
const NODE_PULSE_MS = 1800;
const CAPTURE_SEPARATION = 24;
const CLUSTER_MIN_SOURCES = 4;
const STAR_COUNT = 1500;
const MAX_VISIBLE_LINKS = 6000;
const GROUP_RADIUS = 370;
const NODE_GROUP_SPREAD = 115;
const REDUCED_MOTION = matchMedia('(prefers-reduced-motion: reduce)').matches;
const endpointId = value => typeof value === 'object' ? value.id : value;

export function cameraPlan(response, nodeCount) {
  const sources = [...new Set(Array.isArray(response.nodes) ? response.nodes : [])]
    .filter(id => Number.isInteger(id) && id >= 0 && id < nodeCount);
  if (response.note_question === false || response.intent === 'smalltalk' || response.camera === 'none' || !sources.length) {
    return {mode: 'none', nodes: []};
  }
  return {mode: sources.length >= CLUSTER_MIN_SOURCES ? 'cluster' : 'single', nodes: sources};
}

export class Galaxy {
  constructor(container, onSelect, onChange) {
    this.container = container;
    this.onSelect = onSelect;
    this.onChange = onChange;
    this.nodes = [];
    this.links = [];
    this.active = new Set();
    this.sources = new Set();
    this.objects = new Map();
    this.colors = new Map();
    this.haloTextures = new Map();
    this.flyCount = 0;
    this.flightToken = 0;
    this.revision = -1;
    this.lastMode = 'none';
    this.graph = new ForceGraph3D(container, {controlType: 'orbit'})
      .backgroundColor('#030609').showNavInfo(false)
      .nodeId('id').nodeLabel(node => {
        const tooltip = document.createElement('span');
        tooltip.textContent = node.label;
        tooltip.dir = 'auto';
        return tooltip;
      })
      .nodeThreeObject(node => this.makeNode(node))
      .nodeThreeObjectExtend(false)
      .linkColor(link => this.isActiveLink(link) ? '#98eed3' : '#294251')
      .linkOpacity(.25).linkWidth(link => this.isActiveLink(link) ? 1.2 : .35)
      .linkDirectionalParticles(link => this.isActiveLink(link) ? 2 : 0)
      .linkDirectionalParticleWidth(1.2).linkDirectionalParticleSpeed(.002)
      .onNodeClick(node => this.select(node.id))
      .onNodeHover(node => { container.style.cursor = node ? 'pointer' : 'default'; })
      .cooldownTicks(45).d3VelocityDecay(.6);
    this.graph.cameraPosition({x:0,y:120,z:1050});
    const controls = this.graph.controls();
    controls.autoRotate = !REDUCED_MOTION;
    controls.autoRotateSpeed = IDLE_ROTATION_SPEED;
    controls.enableDamping = true;
    controls.addEventListener('start', () => this.hold());
    this.addStars();
    this.resize();
    window.addEventListener('resize', () => this.resize());
    this.animate();
  }
  resize() { this.graph.width(innerWidth).height(innerHeight); }
  color(group) {
    if (!this.colors.has(group)) this.colors.set(group, GROUP_COLORS[this.colors.size % GROUP_COLORS.length]);
    return this.colors.get(group);
  }
  addStars() {
    const vertices = [];
    for(let i = 0; i < STAR_COUNT; i++) {
      const r = 1100 + Math.random() * 2500;
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      vertices.push(r * Math.sin(phi) * Math.cos(theta), r * Math.cos(phi), r * Math.sin(phi) * Math.sin(theta));
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position',new THREE.Float32BufferAttribute(vertices,3));
    this.graph.scene().add(new THREE.Points(geometry, new THREE.PointsMaterial({color: '#92afbc',size:1.4,transparent:true,opacity:.45,sizeAttenuation:true})));
  }
  makeNode(node) {
    const color = this.color(node.group);
    const group = new THREE.Group();
    const core = new THREE.Mesh(new THREE.SphereGeometry(2.4,16,12),new THREE.MeshBasicMaterial({color}));
    if(!this.haloTextures.has(color)) {
      const canvas = document.createElement('canvas'); canvas.width = canvas.height = 64;
      const ctx = canvas.getContext('2d');
      const gradient = ctx.createRadialGradient(32,32,0,32,32,32);
      gradient.addColorStop(0,'#ffffff'); gradient.addColorStop(.16,color); gradient.addColorStop(1,'transparent');
      ctx.fillStyle = gradient; ctx.fillRect(0,0,64,64);
      this.haloTextures.set(color,new THREE.CanvasTexture(canvas));
    }
    const halo = new THREE.Sprite(new THREE.SpriteMaterial({map:this.haloTextures.get(color),color,transparent:true,opacity:.3,depthWrite:false,blending:THREE.AdditiveBlending}));
    halo.scale.set(22,22,1);
    group.add(core,halo); group.userData = {core,halo,born:node._born || 0};
    this.objects.set(node.id, group);
    return group;
  }
  update(data, birth = null, force = false) {
    if(!Array.isArray(data.nodes) || !Array.isArray(data.links)) throw new Error('נתוני הגלקסיה אינם תקינים.');
    if(!force&&Number.isInteger(data.revision)&&data.revision<this.revision)return;
    this.revision=Number.isInteger(data.revision)?data.revision:this.revision;
    const old = new Map(this.nodes.map(n => [n.id,n]));
    const groups=[...new Set(data.nodes.map(node=>node.group))];
    groups.forEach(group=>this.color(group));
    this.nodes = data.nodes.map((node,index) => {
      if(node.id !== index) throw new Error('מזהי ההערות אינם תואמים למיקום שלהן במפה.');
      const existing = old.get(node.id);
      if(existing) return Object.assign(existing,node);
      const fresh = {...node};
      // A deterministic starting position keeps a large vault usable during boot.
      const groupIndex=groups.indexOf(node.group);
      const theta=groupIndex*2.399963229728653;
      const groupY=1-2*(groupIndex+.5)/Math.max(groups.length,1);
      const radius=groups.length>1?GROUP_RADIUS:0;
      const seed=(index*2654435761>>>0)/4294967296;
      const localTheta=index*2.399963229728653;
      const localRadius=NODE_GROUP_SPREAD*Math.cbrt(seed);
      const localY=2*((index*9301+49297)%233280)/233280-1;
      fresh.x=Math.cos(theta)*Math.sqrt(1-groupY*groupY)*radius+Math.cos(localTheta)*localRadius;
      fresh.y=groupY*radius+localY*localRadius;
      fresh.z=Math.sin(theta)*Math.sqrt(1-groupY*groupY)*radius+Math.sin(localTheta)*localRadius;
      if (birth && node.id === birth.node.id) {
        const related = old.get(birth.related_node);
        Object.assign(fresh,{x:related?.x || 0,y:related?.y || 0,z:related?.z || 0,_born:performance.now()});
        fresh._birthStart={x:fresh.x,y:fresh.y,z:fresh.z};
        const angle=node.id*2.399963229728653;
        fresh._birthOffset={x:Math.cos(angle)*CAPTURE_SEPARATION,y:CAPTURE_SEPARATION*.5,z:Math.sin(angle)*CAPTURE_SEPARATION};
      }
      return fresh;
    });
    this.links = data.links.map(link => ({...link,source:endpointId(link.source),target:endpointId(link.target)}));
    this.visibleLinks=this.links.filter((_,index)=>index%Math.max(1,Math.ceil(this.links.length/MAX_VISIBLE_LINKS))===0).map(link=>({...link}));
    this.graph.graphData({nodes:this.nodes,links:this.visibleLinks});
    if(this.nodes.length>500) {
      // Positions stay stable while navigating; full adjacency remains available.
      this.graph.d3Force('charge',null).d3Force('link',null).d3Force('center',null).cooldownTicks(1);
      this.nodes.forEach(node=>{node.fx=node.x;node.fy=node.y;node.fz=node.z;});
    }
    this.onChange?.(this.nodes,this.colors);
    if(birth) requestAnimationFrame(() => this.select(birth.node.id));
  }
  neighbours(id) {
    return this.links.flatMap(link => endpointId(link.source) === id ? [endpointId(link.target)] : endpointId(link.target) === id ? [endpointId(link.source)] : []);
  }
  isActiveLink(link) { return this.active.has(endpointId(link.source)) && this.active.has(endpointId(link.target)); }
  illuminate(ids, withNeighbours) {
    this.sources = new Set(ids);
    this.active = new Set(ids);
    if(withNeighbours) ids.forEach(id => this.neighbours(id).forEach(n => this.active.add(n)));
    // Draw actual selected relationships from the full graph, including edges
    // omitted from the idle subset. No source or neighbour is invented.
    const sourceSet=new Set(ids);
    const selected=this.links.filter(link=>sourceSet.has(link.source)||sourceSet.has(link.target));
    const rest=this.visibleLinks.filter(link=>!sourceSet.has(endpointId(link.source))&&!sourceSet.has(endpointId(link.target)));
    const linkMap=new Map([...rest,...selected].map(link=>[`${endpointId(link.source)}:${endpointId(link.target)}`,{...link,source:endpointId(link.source),target:endpointId(link.target)}]));
    this.graph.graphData({nodes:this.nodes,links:[...linkMap.values()]});
    this.graph.linkWidth(this.graph.linkWidth()).linkColor(this.graph.linkColor()).linkDirectionalParticles(this.graph.linkDirectionalParticles());
  }
  hold() { this.graph.controls().autoRotate = false; this.flightToken++; }
  select(id, extraSources = []) {
    const node = this.nodes[id]; if(!node) return;
    this.hold(); this.lastMode = 'single';
    this.illuminate([id,...extraSources],true);
    const vector = new THREE.Vector3(node.x || 0,node.y || 0,node.z || 0);
    const offset = vector.clone().normalize().multiplyScalar(105);
    if(offset.length() < 1) offset.set(0,20,105);
    const destination=vector.clone().add(offset);
    const cameraStart=this.graph.camera().position.clone();
    const targetStart=this.graph.controls().target.clone();
    const token=this.flightToken;
    const started=performance.now();
    const fly=now=>{
      if(token!==this.flightToken)return;
      const progress=REDUCED_MOTION?1:Math.min(1,(now-started)/FLY_DURATION_MS);
      const eased=1-Math.pow(1-progress,3);
      this.graph.cameraPosition(cameraStart.clone().lerp(destination,eased),targetStart.clone().lerp(vector,eased),0);
      if(progress<1)requestAnimationFrame(fly);
    };
    requestAnimationFrame(fly);
    this.flyCount++;
    this.onSelect?.(node,this.neighbours(id).map(i => this.nodes[i]).filter(Boolean));
  }
  prove(response) {
    this.hold();
    const plan = cameraPlan(response,this.nodes.length);
    this.lastMode = plan.mode;
    if(plan.mode === 'single') this.select(plan.nodes[0],plan.nodes.slice(1));
    if(plan.mode === 'cluster') this.illuminate(plan.nodes,false);
    return plan;
  }
  fit() { this.active.clear(); this.sources.clear(); this.graph.zoomToFit(REDUCED_MOTION ? 0 : 1000,100); this.graph.controls().autoRotate = !REDUCED_MOTION; this.lastMode = 'overview'; }
  animate() {
    const now = performance.now();
    for(const [id,group] of this.objects) {
      const active = this.active.has(id);
      const source = this.sources.has(id);
      const hasSelection = this.active.size > 0;
      const born = group.userData.born;
      const node=this.nodes[id];
      if(node?._birthStart){
        const progress=Math.min(1,(now-born)/NODE_PULSE_MS);
        for(const axis of ['x','y','z']){
          node[axis]=node._birthStart[axis]+node._birthOffset[axis]*(1-Math.pow(1-progress,3));
          if(this.nodes.length>500)node[`f${axis}`]=node[axis];
        }
        group.position.set(node.x,node.y,node.z);
        if(progress===1){delete node._birthStart;delete node._birthOffset;}
      }
      const pulse = born && now - born < NODE_PULSE_MS ? Math.sin((now - born)/NODE_PULSE_MS * Math.PI) : 0;
      group.userData.core.scale.setScalar(source ? 1.7 : active ? 1.25 : 1);
      group.userData.core.material.opacity = hasSelection && !active ? .32 : 1;
      group.userData.core.material.transparent = true;
      group.userData.halo.material.opacity = pulse ? .85 : source ? .8 : active ? .48 : hasSelection ? .07 : .23;
      const size = 22 + (source ? 12 : 0) + pulse * 50;
      group.userData.halo.scale.set(size,size,1);
    }
    requestAnimationFrame(() => this.animate());
  }
  inspection() { return {nodeCount:this.nodes.length,linkCount:this.links.length,visibleLinkCount:this.graph.graphData().links.length,flyCount:this.flyCount,mode:this.lastMode,litCount:this.active.size,rendered:!!this.container.querySelector('canvas'),rotation:this.graph.controls().autoRotate}; }
}
