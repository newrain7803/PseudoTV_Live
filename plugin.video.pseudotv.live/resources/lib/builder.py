#   Copyright (C) 2020 Lunatixz
#
#
# This file is part of PseudoTV Live.
#
# PseudoTV Live is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# PseudoTV Live is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with PseudoTV Live.  If not, see <http://www.gnu.org/licenses/>.

# -*- coding: utf-8 -*-

from resources.lib.globals    import *
from resources.lib.parser     import Writer, Channels, JSONRPC

class Builder:
    def __init__(self):
        self.log('__init__')
        self.writer           = Writer()
        self.channels         = Channels()
        self.jsonRPC          = JSONRPC()
        self.incStrms         = INCLUDE_STRMS  #todo adv. rules
        self.incExtras        = INCLUDE_EXTRAS #todo adv. rules
        self.maxDays          = MAX_GUIDE_DAYS
        self.fillBCTs         = ENABLE_BCTS
        self.grouping         = ENABLE_GROUPING
        self.accurateDuration = ACCURATE_DURATION
        self.filter           = {}
        self.sort             = {}
        self.limits           = {}
        self.limit            = PAGE_LIMIT
        self.now              = getLocalTime()
        self.start            = roundToHalfHour(self.now)
        self.dialog           = None
        self.progress         = 0
        self.channelCount     = 0
        self.msg              = ''
        
        self.bctTypes         = {"rating"    :{"min":0,"max":0,"enabled":True  ,"path":GLOBAL_RESOURCE_PACK_RATINGS},
                                 "trailer"   :{"min":0,"max":2,"enabled":False ,"path":GLOBAL_RESOURCE_PACK_TRAILERS},
                                 "bumper"    :{"min":0,"max":0,"enabled":False ,"path":GLOBAL_RESOURCE_PACK_BUMPERS},
                                 "commercial":{"min":0,"max":0,"enabled":False ,"path":GLOBAL_RESOURCE_PACK_COMMERICALS}}#todo check adv. rules get settings
                                 
    def log(self, msg, level=xbmc.LOGDEBUG):
        return log('%s: %s'%(self.__class__.__name__,msg),level)
    

    def runActions(self, action, channel, parameter=None):
        self.log("runActions action = %s, channel = %s"%(action,channel))
        if not channel.get('id',''): return parameter
        chrules = sorted(self.channels.getChannelRules(channel), key=lambda k: k['id'])
        for chrule in chrules:
            ruleInstance = chrule['action']
            if ruleInstance.actions & action > 0:
                parameter = ruleInstance.runAction(action, self, parameter)
        return parameter


    def createChannelItems(self):
        self.log('createChannelItems')
        if self.channels.reset():
            items = self.channels.getAllChannels()
            for idx, item in enumerate(items):
                # item = self.runActions(RULES_ACTION_CHANNEL_CREATION, item, itemk)
                if (not item.get('name','') or not item.get('path',None) or item.get('number',0) < 1): 
                    self.log('createChannelItems; skipping, missing channel path and/or channel name\n%s'%(dumpJSON(item)))
                    continue
                    
                item['label']  = item['name']
                item['id']     = (item.get('id','')    or getChannelID(item['name'], item['path'], item['number'])) # internal use only; use provided id for future xmltv pairing, else create unique Pseudo ID.
                item['logo']   = (item.get('logo','')  or self.jsonRPC.getLogo(item['name'], item['type'], item['path'], featured=True))
                item['radio']  = (item.get('radio','') or (item['type'] == 'MUSIC Genres' or item['path'][0].startswith('musicdb://')))
                item['url']    = 'plugin://%s/?mode=play&name=%s&id=%s&radio=%s'%(ADDON_ID,urllib.parse.quote(item['name']),urllib.parse.quote(item['id']),str(item['radio']))
                # if item['xmltv']: self.parseXMLTV(item['id']) #todo opt for url xmltv file with matching id.

                if not self.grouping: 
                    item['group'] = [ADDON_NAME]
                else:
                    item['group'].append(ADDON_NAME)
                yield item


    def buildService(self, channels=None, update=False):
        if isBusy(): return
        elif self.channels.isClient:
            self.log('buildService, Client mode enabled; returning!')
            return False
        elif not self.writer.reset(): 
            self.log('buildService, initializing m3u/xmltv parser failed!')
            return False
            
        self.log('buildService, channels = %s, update = %s'%(len(channels),update))
        if channels is None: 
            channels = sorted(self.createChannelItems(), key=lambda k: k['number'])
            
        if not channels:
            notificationDialog(LANGUAGE(30056))
            return False

        setBusy(True)
        msg = LANGUAGE(30051 if update else 30050)
        self.dialog = ProgressBGDialog(message=LANGUAGE(30052)%('...'))
        
        self.channelCount = len(channels)
        if getProperty('PseudoTVRunning') != 'True': # legacy setting to disable/enable support in third-party applications. 
            setProperty('PseudoTVRunning','True')
            
        for idx, channel in enumerate(channels):
            channel       = self.runActions(RULES_ACTION_START, channel, channel)
            self.msg      = channel['name']
            self.progress = (idx*100//len(channels))
            cacheResponse = self.getFileList(channel, channel['radio']) # {True:'Valid Channel exceed MAX_DAYS',False:'In-Valid Channel',list:'fileList'}
            cacheResponse = self.runActions(RULES_ACTION_STOP, channel, cacheResponse)
            if not cacheResponse: continue
            self.writer.addChannel(channel, channel['radio'], not bool(channel['radio']))
            if isinstance(cacheResponse,list):
                self.dialog = ProgressBGDialog(self.progress, self.dialog, message='%s, %s'%(msg,self.msg))
                self.writer.addProgrammes(channel, cacheResponse, channel['radio'], not bool(channel['radio']))
                
        if not self.writer.save(): 
            notificationDialog(LANGUAGE(30001))
        setBusy(False)
        self.dialog = ProgressBGDialog(100, self.dialog, message=LANGUAGE(30053))
        self.log('buildService, finished')
        if not self.jsonRPC.myPlayer.isPlaying() and getProperty('PseudoTVRunning') == 'True': # legacy setting to disable/enable support in third-party applications. 
            setProperty('PseudoTVRunning','True')
        return True
            

    def getFileList(self, channel, radio=False):
        self.log('getFileList; channel = %s, radio = %s'%(channel,radio))
        try:
            # global values prior to channel rules
            self.filter = {}
            self.sort   = {}#{"order": "ascending", "ignorefolders": "false", "method": "random"}
            self.limits = {}#adv. rule to force page.
            self.limit  = PAGE_LIMIT
            self.now    = getLocalTime()
            self.start  = (self.writer.endtimes.get(channel['id'],'') or roundToHalfHour(self.now)) #offset time to start on half hour

            self.runActions(RULES_ACTION_CHANNEL_START, channel, Builder)
            if datetime.datetime.fromtimestamp(self.start) >= (datetime.datetime.fromtimestamp(self.now) + datetime.timedelta(days=self.maxDays)): 
                self.log('getFileList, id: %s programmes exceed MAX_DAYS: endtime = %s'%(channel['id'],self.start),xbmc.LOGINFO)
                return True# prevent over-building
                
            # channel = self.runActions(RULES_ACTION_CHANNEL_JSON, channel, self)
            if isinstance(channel['path'], list): 
                mixed = True # build 'mixed' channels ie more than one path.
                path  = channel['path']
            else:
                mixed = False
                path  = [channel['path']] 
                
            limit = int(self.limit//len(path))# equally distribute content between multi-paths.
            media = 'music' if radio else 'video'
            if radio:
                cacheResponse = self.buildRadioList(channel)
            else:         
                cacheResponse = [self.buildFileList(channel, file, media, limit, self.sort, self.filter, self.limits) for file in path] # build multi-paths as induvial arrays for easier interleaving.
                if not cacheResponse: 
                    self.log("getFileList, id: %s skipping channel cacheResponse empty!"%(channel['id']),xbmc.LOGINFO)
                    return False
                
                cacheResponse = self.runActions(RULES_ACTION_CHANNEL_LIST, channel, cacheResponse)
                cacheResponse = list(interleave(*cacheResponse)) # interleave multi-paths, while keeping order.
                # cacheResponse = removeDupsDICT(cacheResponse) # remove duplicates, back-to-back duplicates target range.
                # if len(cacheResponse) < limit: # balance media limits, by filling randomly with duplicates.
                    # cacheResponse.extend(list(fillList(cacheResponse,(limit-len(cacheResponse)))))

            cacheResponse = self.addScheduling(channel, cacheResponse)
            if self.fillBCTs: 
                cacheResponse = self.injectBCTs(channel, cacheResponse)
            self.runActions(RULES_ACTION_CHANNEL_STOP, channel, Builder)
            return sorted((cacheResponse), key=lambda k: k['start'])
        except Exception as e: self.log("getFileList, Failed! " + str(e), xbmc.LOGERROR)
        return False
            

    def injectBCTs(self, channel, fileList):
        if channel['radio'] == True: 
            return fileList
        
        def buildBCT(bctType, path):
            if path.startswith(('pvr://','upnp://','plugin://')): return # Kodi only handles stacks between local content, bug?
            duration = self.jsonRPC.parseDuration(path)
            self.log("injectBCTs; buildBCT building %s, path = %s, duration = %s"%(bctType,path,duration))
            if bctType in PRE_ROLL:
                paths.insert(0,path)
            else:
                paths.append(path)
                item['stop'] += duration
                          
        tmpList     = []
        resourceMap = {}
        self.log("injectBCTs; channel = %s, configuration = %s, fileList size = %s"%(channel,dumpJSON(bctTypes),len(fileList)))
        
        bctTypes = self.bctTypes
        for bctType in bctTypes:
            if not bctTypes[bctType]['enabled']: continue
            resourceMap[bctType] = self.jsonRPC.buildBCTresource(bctTypes[bctType].get('path'))
            if bctType in ['bumper','commercial']: # locate folder by channel name.
                self.log("injectBCTs; finding channel folder %s for %s"%(channel['name'],bctType))
                resourceMap[bctType] = [self.jsonRPC.buildBCTresource(os.path.join(bctTypes[bctType].get('path'),dir)) for dir in bctTypes[bctType].get('dirs') if channel['name'].lower() == dir.lower()]
            elif bctTypes == 'trailer':        
                # integrate channel trailers along with resources
                trailers = filter(None,list(set([fileitem.get('trailer',None) for fileitem in fileList])))
                if not trailers: continue
                trailers = trailers.reverse()
                trailers.shuffle()
                self.log("injectBCTs; adding %s local kodi trailers"%(len(trailers)))
                resourceMap[bctType]['filepaths'].extend(trailers)
                   
        for item in fileList:
            stop      = item['stop']
            endOnHour = (roundToHour(stop) - stop)
            file      = item['file']
            stack     =  'stack://%s'
            if   file.startswith(('pvr://','upnp://','plugin://')): continue # Kodi only handles stacks between local content, bug?
            elif file.startswith('stack://'):
                paths = splitStack(file)
            else:
                paths = [file]
            orgPaths  = paths.copy()

            for bctType in bctTypes:
                if not bctTypes[bctType]['enabled']: continue
                resource  = resourceMap.get(bctType,{})
                files     = resource.get('files',[])
                filepaths = resource.get('filepaths',[])
                
                if bctType == 'rating':
                    mpaa = item.get('mpaa'  ,'')
                    if mpaa.startswith('Rated'): mpaa = re.split('Rated ',mpaa)[1]  #todo prop. regex
                    if is3D(item): mpaa += ' (3DSBS)'
                    for file in files:
                        rating = os.path.splitext(file)[0]
                        if rating.lower() == mpaa.lower():
                            buildBCT(bctType,self.jsonRPC.buildResourcePath(resource['path'],file))
                else:
                    max = bctTypes[bctType].get('max',0)
                    if max > len(filepaths): max = len(filepaths)
                    matches = random.sample(filepaths, random.randint(bctTypes[bctType].get('min',0),max))
                    [buildBCT(bctType, match) for match in matches]
                                    
            if orgPaths != paths:
                item['originalfile'] = item['file']
                item['file'] = stack%(' , '.join(paths))
            tmpList.append(item)
        return tmpList

        
    def addScheduling(self, channel, fileList):
        self.log("addScheduling; channel = %s"%(channel))
        #todo insert adv. scheduling rules here or move to adv. rules.py
        tmpList  = []
        fileList = self.runActions(RULES_ACTION_CHANNEL_BEFORE_TIME, channel, fileList)
        for idx, item in enumerate(fileList):
            item["idx"]   = idx
            item['start'] = self.start
            item['stop']  = self.start + item['duration']
            self.start    = item['stop']
            tmpList.append(item)
        tmpList = self.runActions(RULES_ACTION_CHANNEL_AFTER_TIME, channel, tmpList)
        return tmpList
            

    def buildRadioList(self, channel):
        self.log("buildRadioList; channel = %s"%(channel))
        #todo insert custom radio labels,plots based on genre type?
        channel['genre'] = [channel['name']]
        channel['art']   = {'thumb':channel['logo'],'icon':channel['logo'],'fanart':channel['logo']}
        channel['plot']  = LANGUAGE(30098)%(channel['name'])
        return self.buildSingleCell(channel,type='music')
                
                
    def buildSingleCell(self, channel, duration=10800, type='video', entries=3):
        self.log("buildSingleCell; channel = %s"%(channel))
        tmpItem  = {'label'       : (channel.get('label','') or channel['name']),
                    'episodetitle': channel.get('episodetitle',''),
                    'plot'        : (channel.get('plot' ,'') or xbmc.getLocalizedString(161)),
                    'genre'       : channel.get('genre',['Undefined']),
                    'type'        : type,
                    'duration'    : duration,
                    'start'       : 0,
                    'stop'        : 0,
                    'art'         : channel.get('art',{})}
        return [tmpItem.copy() for idx in range(entries)]
        
        
    def buildFileList(self, channel, path, media='video', limit=PAGE_LIMIT, sort={}, filter={}, limits={}):
        self.log("buildFileList, path = %s, limit = %s, sort = %s, filter = %s, limits = %s"%(path,limit,sort,filter,limits))
        if path.startswith('videodb://movies'): 
            if not sort: sort = {"method": "random"}
        elif path.startswith('plugin://script.embuary.helper/?info=getseasonal&amp;list={list}&limit={limit}'):
            if not sort: sort = {"method": "episode"}
            path = path.format(list=getSeason(),limit=250)
            
        id = channel['id']
        fileList      = []
        seasoneplist  = []
        method        =  sort.get("method","random")
        json_response = self.jsonRPC.requestList(id, path, media, limit, sort, filter, limits)

        for item in json_response:
            item = self.runActions(RULES_ACTION_CHANNEL_ITEM, channel, item)
            file = item.get('file','')
            fileType = item.get('filetype','file')

            if fileType == 'file':
                if file[-4].lower() == 'strm' and not self.incStrms: 
                    self.log("buildFileList, id: %s skipping strm!"%(id),xbmc.LOGINFO)
                    continue
                    
                dur = self.jsonRPC.getDuration(file, item, self.accurateDuration)
                if dur > 0:
                    item['duration'] = dur
                    if int(item.get("year","0")) == 1601: 
                        item['year'] = 0 #default null for kodi rpc?
                    mType   = item['type']
                    label   = item['label']
                    title   = (item.get("title",'') or label)
                    tvtitle = (item.get("showtitle","") or item.get("tvshowtitle",""))

                    if tvtitle:
                        # This is a TV show
                        seasonval = int(item.get("season","0"))
                        epval     = int(item.get("episode","0"))
                        if not self.incExtras and (seasonval == 0 or epval == 0) and item.get("episode",None) is not None: 
                            self.log("buildFileList, id: %s skipping extras!"%(id),xbmc.LOGINFO)
                            continue
                            
                        # if epval > 0: 
                            # item["episodetitle"] = title + ' (' + str(seasonval) + 'x' + str(epval).zfill(2) + ')'
                        # else:
                        label = tvtitle
                        item["tvshowtitle"]  = tvtitle
                        item["episodetitle"] = title
                        
                    else: # This is a Movie
                        years = int(item.get("year","0"))
                        if years > 0: title = "%s (%s)"%(title, years)
                        item["episodetitle"] = item.get("tagline","")
                        seasonval = None
                        label = title
            
                    if not label: continue
                    item['label'] = label
                    item['plot']  = (item.get("plot","") or item.get("plotoutline","") or item.get("description","") or xbmc.getLocalizedString(161))
            
                    if self.dialog is not None:
                        self.dialog = ProgressBGDialog(self.progress, self.dialog, message='%s: %s'%(self.msg,((len(fileList)*100)//PAGE_LIMIT))+'%')
                    
                    #unify artwork
                    item.get('art',{})['icon']  = channel['logo']
                    # item.get('art',{})['thumb'] = getThumb(item)
                    
                    #parsing missing meta
                    if not item.get('streamdetails',{}).get('video',[]): 
                        item['streamdetails'] = self.jsonRPC.getStreamDetails(file, media)

                    if method == 'episode' and seasonval is not None: 
                        seasoneplist.append([seasonval, epval, item])
                    else: 
                        fileList.append(item)
                else: 
                    self.log("buildFileList, id: %s skipping no duration meta found!"%(id),xbmc.LOGINFO)
                    
            elif fileType == 'directory' and (len(fileList) < limit): #extend fileList by parsing folders, limit folder parsing to limit size to avoid runaways.
                fileList.extend(self.buildFileList(channel, file, media, limit, sort, filter, limits))
            
        if method == 'episode':
            seasoneplist.sort(key=lambda seep: seep[1])
            seasoneplist.sort(key=lambda seep: seep[0])
            for seepitem in seasoneplist: 
                fileList.append(seepitem[2])
            
        self.log("buildFileList, id: %s returning fileList %s / %s"%(id,len(fileList),limit),xbmc.LOGINFO)
        return fileList