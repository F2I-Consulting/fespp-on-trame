# fetpapi — le client ETP

Source : documentation rédigée pour fespp_on_trame à partir des sources du projet fetpapi (F2I Consulting, licence Apache-2.0), version 0.4.0.0.

### Ce qu'est fetpapi (what fetpapi is)
fetpapi est une bibliothèque C++ open source pour écrire un client ETP 1.2 (Energistics Transfer Protocol ; voir ETP dans le glossaire), le standard par défaut pour dialoguer avec le RDDMS d'OSDU. Elle s'appuie sur Boost.Beast pour le WebSocket et sur Avro pour les messages, et peut s'intégrer à fesapi (option WITH_FESAPI). La version 0.4.0.0 ne contient que des sessions client.

fetpapi is an open-source C++ library to write an ETP 1.2 client, the default standard to talk to the OSDU RDDMS. It uses Boost.Beast for the WebSocket and Avro for messages, and can integrate with fesapi (WITH_FESAPI option). Version 0.4.0.0 only contains client sessions.

### Construction et langages (build and languages)
Dépendances : Boost (1.66 ou plus, avec des soucis connus en 1.72 et 1.73), Avro (1.9.0 ou plus, sauf 1.11.1), OpenSSL en option (3.4 connu pour marcher), fesapi en option (2.7.0.0 au moins, 2.11.0.0 recommandé). SWIG génère des liaisons Python 3, C# et Java ; en Python : import fetpapi, puis fetpapi.InitializationParameters et fetpapi.createClientSession.

Dependencies: Boost 1.66 or later, Avro 1.9.0 or later (except 1.11.1), optional OpenSSL (3.4 known to work), optional fesapi (2.7.0.0 minimum, 2.11.0.0 recommended). SWIG generates Python 3, C# and Java wrappers; in Python: import fetpapi, then fetpapi.InitializationParameters and fetpapi.createClientSession.

### ETP 1.2 en bref (ETP 1.2 in brief)
ETP 1.2 échange des messages binaires Avro sur un WebSocket dont le sous-protocole est « etp12.energistics.org ». Chaque message appartient à un protocole numéroté (Core, Discovery, Store…) et porte un en-tête avec un identifiant ; une réponse cite l'identifiant de la demande (correlationId). Le serveur, ou store, range ses objets dans des dataspaces ; objets et dataspaces sont nommés par des URI ; les grands tableaux voyagent à part (protocole DataArray).

ETP 1.2 exchanges binary Avro messages over a WebSocket whose subprotocol is "etp12.energistics.org". Each message belongs to a numbered protocol and carries a header with an id; a response quotes the request id (correlationId). The store keeps objects in dataspaces, named by URIs; large arrays travel separately (DataArray protocol).

### Protocoles numérotés (numbered protocols)
L'énumération Protocol donne les numéros ETP 1.2 : Core 0, ChannelStreaming 1, ChannelDataFrame 2, Discovery 3, Store 4, StoreNotification 5, GrowingObject 6, DataArray 9, DiscoveryQuery 13, StoreQuery 14, Transaction 18, ChannelSubscribe 21, ChannelDataLoad 22, Dataspace 24, SupportedTypes 25, et deux extensions OSDU : StoreOSDU 2404 et DataspaceOSDU 2424. fetpapi fournit des gestionnaires pour Core, Discovery, Store, StoreNotification, DataArray, Transaction, Dataspace et les deux OSDU.

The Protocol enum gives the ETP 1.2 numbers: Core 0, Discovery 3, Store 4, StoreNotification 5, DataArray 9, Transaction 18, Dataspace 24, SupportedTypes 25, plus OSDU extensions StoreOSDU 2404 and DataspaceOSDU 2424. fetpapi ships handlers for Core, Discovery, Store, StoreNotification, DataArray, Transaction, Dataspace and both OSDU protocols.

### URI et dataspaces (URIs and dataspaces)
Une URI ETP 1.2 nomme un dataspace ou un objet : « eml:/// » est le dataspace par défaut, « eml:///dataspace('project/study') » un dataspace nommé, et l'URI d'un objet ajoute son type et son uuid. EtpHelpers extrait d'une URI le type d'objet (getDataObjectType), l'URI de son dataspace (getDataspaceUri), l'uuid et la version (getUuidAndVersionFromUri), et valide une URI (validateUri, validateDataObjectUri).

An ETP 1.2 URI names a dataspace or an object: "eml:///" is the default dataspace, "eml:///dataspace('project/study')" a named one, and an object URI adds its type and uuid. EtpHelpers extracts the object type (getDataObjectType), the dataspace URI (getDataspaceUri), the uuid and version, and validates URIs.

### Paramètres d'initialisation (InitializationParameters)
InitializationParameters décrit la connexion : un uuid d'instance et l'URL du serveur, « ws://hôte:port/chemin » ou « wss://… » (port par défaut 80, ou 443 en wss), plus une URL de proxy optionnelle ; ou bien hôte, port et chemin séparés. setAdditionalHandshakeHeaderFields ajoute des en-têtes à la poignée de main, comme data-partition-id pour OSDU ; setAdditionalCertificates, setForceTls, setMaxWebSocketMessagePayloadSize (16 000 000 octets par défaut) complètent.

InitializationParameters describes the connection: an instance uuid and the server URL, "ws://host:port/path" or "wss://…" (default port 80, or 443 for wss), plus an optional proxy URL; or separate host, port and path. setAdditionalHandshakeHeaderFields adds handshake headers such as data-partition-id for OSDU; setForceTls and payload size setters complete it.

### Protocoles et objets déclarés (requested protocols and supported data objects)
Par défaut, makeSupportedProtocols demande Discovery, Store, StoreNotification, DataArray, Transaction, Dataspace, StoreOSDU et DataspaceOSDU en version 1.2, le serveur tenant le rôle « store ». makeSupportedDataObjects déclare resqml20.*, resqml22.*, eml20.obj_EpcExternalPartReference et des types eml23 (Activity, PropertyKind, TimeSeries…) avec get, put et delete. On dérive la classe pour changer ces listes ou le nom d'application (« F2I-CONSULTING ETP CLIENT »).

By default makeSupportedProtocols requests Discovery, Store, StoreNotification, DataArray, Transaction, Dataspace and the OSDU protocols in version 1.2, the server acting as "store". makeSupportedDataObjects declares resqml20.*, resqml22.* and some eml types with get, put and delete. Derive the class to change these lists.

### En-tête d'autorisation (authorization header)
createClientSession reçoit la valeur de l'en-tête HTTP d'autorisation du serveur ETP, « en général Bearer suivi d'un jeton », et une autre pour un proxy protégé ; elle peut être vide. Le schéma Basic marche aussi : l'exemple Python envoie « Basic » suivi de « foo:bar » (utilisateur:mot de passe) encodé en base64. FESPP compose l'en-tête « <type> <jeton> » sans encoder le jeton.

createClientSession takes the value of the ETP server's HTTP authorization header, "generally Bearer followed by a token", and another for a protected proxy; it may be empty. Basic also works: the Python example sends "Basic" followed by the base64 encoding of "foo:bar" (user:password). FESPP builds "<type> <token>" without encoding the token.

### Créer une session (ClientSessionLaunchers)
ClientSessionLaunchers::createClientSession interroge d'abord en HTTP(S) « /.well-known/etp-server-capabilities?GetVersion=etp12.energistics.org » pour négocier la taille des trames WebSocket, puis crée une PlainClientSession, ou une SslClientSession si le port est 443 ou TLS forcé (fetpapi compilé avec WITH_ETP_SSL). Elle enregistre les gestionnaires par défaut mais ne lance pas la session : il faut appeler run.

createClientSession first queries the server capabilities over HTTP(S) to negotiate the WebSocket frame size, then creates a PlainClientSession, or an SslClientSession when the port is 443 or TLS is forced (built WITH_ETP_SSL). It registers default handlers but does not run the session: call run.

### Ouverture de session (RequestSession, OpenSession)
Après la poignée de main WebSocket, le client envoie Core.RequestSession : nom et version d'application, uuid d'instance, protocoles demandés, objets pris en charge, format « xml », capacités. Le serveur répond Core.OpenSession avec l'identifiant de session (getIdentifier) ; fetpapi réduit sa taille maximale de message si celle du serveur est plus petite. isEtpSessionClosed passe alors à faux. Le client n'utilise que des identifiants de message pairs non nuls.

After the WebSocket handshake the client sends Core.RequestSession: application name and version, instance uuid, requested protocols, supported objects, "xml" format, capabilities. The server answers Core.OpenSession with the session id; fetpapi lowers its maximum message size if the server's is smaller. isEtpSessionClosed then turns false.

### Boucle et fil d'exécution (run loop and threading)
ClientSession::run résout le nom, se connecte, puis traite tout dans une seule boucle d'événements sur le fil appelant, gestionnaires compris ; elle ne rend la main qu'à la fermeture. On la lance donc sur un fil dédié, puis on attend que isEtpSessionClosed devienne faux (5 secondes dans les exemples). Si la connexion tombe sans fermeture demandée, run tente jusqu'à 10 reconnexions.

ClientSession::run resolves the host, connects, then handles everything in a single event loop on the calling thread, handlers included; it returns only when the session closes. Run it on a dedicated thread and wait for isEtpSessionClosed to turn false (5 seconds in the examples). On an unrequested drop, run retries up to 10 reconnections.

### Envoyer un message (send, sendAndBlock)
send met un message en file et rend son identifiant ; la réponse arrive plus tard dans les gestionnaires du protocole. sendAndBlock bloque le fil jusqu'au traitement de la réponse, avec un délai réglé par setTimeOut (10 000 ms par défaut). sendWithSpecificHandler et sendWithSpecificHandlerAndBlock confient la réponse à un gestionnaire propre à ce message. isMessageStillProcessing dit si une demande attend encore sa réponse ; le drapeau 0x10 demande un accusé de réception.

send queues a message and returns its id; the response later reaches the protocol handlers. sendAndBlock blocks until the response is processed, with a timeout set by setTimeOut (10,000 ms by default). The WithSpecificHandler variants route the response to a handler dedicated to that message.

### Gestionnaires de protocole (ProtocolHandlers)
Chaque protocole a une classe dérivée de ProtocolHandlers qui décode les messages reçus (decodeMessageBody) et appelle une méthode virtuelle on_<Message>. Les gestionnaires par défaut journalisent ou stockent les réponses ; une application les dérive et les enregistre par setCoreProtocolHandlers, setDiscoveryProtocolHandlers, setStoreProtocolHandlers, setDataArrayProtocolHandlers… ou en surchargeant postSessionCreationOperation.

Each protocol has a ProtocolHandlers subclass that decodes incoming messages (decodeMessageBody) and calls a virtual on_<Message> method. Default handlers log or store responses; an application derives them and registers them through the set…ProtocolHandlers methods or by overriding postSessionCreationOperation.

### Core (CoreHandlers)
CoreHandlers traite le protocole 0 : RequestSession, OpenSession, CloseSession, ProtocolException, Acknowledge, Ping, Pong, Authorize et AuthorizeResponse. À l'ouverture il mémorise l'identifiant de session ; à la réception de CloseSession il ferme la connexion ; une ProtocolException porte le code et le message d'erreur du serveur. close envoie CloseSession après les messages en attente, sans bloquer ; closeAndBlock bloque.

CoreHandlers handles protocol 0: RequestSession, OpenSession, CloseSession, ProtocolException, Acknowledge, Ping, Pong, Authorize and AuthorizeResponse. It records the session id on open and closes the connection on CloseSession; a ProtocolException carries the server's error. close sends CloseSession after pending messages without blocking; closeAndBlock blocks.

### Discovery (DiscoveryHandlers)
Discovery (protocole 3) découvre les objets d'un store. getResources envoie GetResources avec un contexte (URI de départ, profondeur, types voulus, arêtes navigables) et une portée : self, sources, sourcesOrSelf, targets ou targetsOrSelf ; il bloque et rend des Resource (URI, nom, compteurs de relations si countObjects). getDeletedResources liste les objets supprimés d'un dataspace. DiscoveryHandlers traite aussi GetResourcesEdgesResponse.

Discovery (protocol 3) discovers objects in a store. getResources sends GetResources with a context (start URI, depth, wanted types, navigable edges) and a scope: self, sources, sourcesOrSelf, targets or targetsOrSelf; it blocks and returns Resource records. getDeletedResources lists deleted objects of a dataspace.

### Store (StoreHandlers)
Store (protocole 4) lit et écrit les objets eux-mêmes. getDataObjects envoie GetDataObjects pour une table clé → URI et rend, par clé, un DataObject : sa Resource et son XML (data). putDataObjects ajoute ou met à jour des objets et rend les clés réussies ; deleteDataObjects supprime. Un objet trop gros arrive en morceaux (Chunk). Ces appels bloquent ; les versions asynchrones passent par send et StoreHandlers.

Store (protocol 4) reads and writes the objects themselves. getDataObjects sends GetDataObjects for a key → URI map and returns, per key, a DataObject: its Resource and its XML (data). putDataObjects adds or updates objects and returns the successful keys; deleteDataObjects deletes. Large objects arrive in Chunk messages.

### StoreNotification (StoreNotificationHandlers)
StoreNotification (protocole 5) abonne le client aux changements d'un store : SubscribeNotifications et UnsubscribeNotifications, puis des notifications ObjectChanged, ObjectDeleted, ObjectAccessRevoked, ObjectActiveStatusChanged, UnsolicitedStoreNotifications et SubscriptionEnded. L'exemple C++ propose une commande SubscribeNotif avec URI, portée, profondeur et filtre de types. Aucune aide bloquante n'existe pour ce protocole : les messages partent par send.

StoreNotification (protocol 5) subscribes the client to store changes: SubscribeNotifications and UnsubscribeNotifications, then ObjectChanged, ObjectDeleted, ObjectAccessRevoked, ObjectActiveStatusChanged, UnsolicitedStoreNotifications and SubscriptionEnded notifications. There is no blocking helper for it: messages go through send.

### DataArray (DataArrayHandlers)
DataArray (protocole 9) transporte les grands tableaux, repérés par l'URI de l'objet et le chemin du tableau (pathInResource, le chemin HDF5 d'un EPC). GetDataArrayMetadata donne dimensions, type et dimensions de sous-tableau préférées ; GetDataArrays lit un tableau entier ; GetDataSubarrays en lit des blocs (starts, counts) ; PutDataArrays, PutDataSubarrays et PutUninitializedDataArrays écrivent. GetFullDataArrayHandlers remplit un tampon fourni.

DataArray (protocol 9) carries large arrays, identified by the object URI and the array path (pathInResource). GetDataArrayMetadata gives dimensions and type; GetDataArrays reads a whole array; GetDataSubarrays reads blocks (starts, counts); the Put messages write. GetFullDataArrayHandlers fills a provided buffer.

### Dataspace (DataspaceHandlers)
Dataspace (protocole 24) gère les dataspaces d'un store. getDataspaces envoie GetDataspaces, avec un filtre optionnel de date de dernière écriture, et rend des Dataspace (URI, chemin…) ; putDataspaces crée ou met à jour des dataspaces, deleteDataspaces les supprime, chacun rendant les clés réussies. Ces aides bloquent jusqu'à la réponse et supposent les gestionnaires par défaut.

Dataspace (protocol 24) manages a store's dataspaces. getDataspaces sends GetDataspaces, with an optional last-write filter, and returns Dataspace records (URI, path…); putDataspaces creates or updates, deleteDataspaces deletes, each returning the successful keys. These helpers block and assume the default handlers.

### Transaction (TransactionHandlers)
Transaction (protocole 18) garantit que les get et put d'une même transaction voient un état cohérent du store, utile aux longues écritures de modèles RESQML. Une session n'a qu'une transaction ouverte à la fois. startTransaction(dataspaces, lecture seule) l'ouvre ; commitTransaction la valide, rollbackTransaction l'annule ; chacun rend une chaîne vide ou le message d'échec. Dans l'en-tête, les commentaires de ces deux méthodes sont intervertis.

Transaction (protocol 18) ensures that gets and puts of one transaction see a consistent store state, useful for long RESQML model writes. A session has a single open transaction. startTransaction opens it; commitTransaction commits, rollbackTransaction cancels; each returns an empty string or the failure. In the header, the comments of these two methods are swapped.

### Extensions OSDU (StoreOSDU, DataspaceOSDU)
Deux protocoles propres à OSDU complètent ETP. DataspaceOSDU (2424) : getDataspaceInfo, lockDataspaces (un dataspace verrouillé porte les données « locked » et « read-only »), copyDataspacesContent et copyToDataspace (copies par référence). StoreOSDU (2404) : copyDataObjectsByValue copie un objet par valeur dans son dataspace, avec des sources choisies par type. Toutes ces aides bloquent.

Two OSDU-specific protocols complement ETP. DataspaceOSDU (2424): getDataspaceInfo, lockDataspaces, copyDataspacesContent and copyToDataspace (copies by reference). StoreOSDU (2404): copyDataObjectsByValue copies an object by value within its dataspace. All these helpers block.

### Pont fesapi : FesapiHdfProxy (fesapi bridge: FesapiHdfProxy)
FesapiHdfProxy est un proxy HDF de fesapi qui lit les tableaux par ETP au lieu d'un .h5 local : chaque lecture demande GetDataArrayMetadata, puis GetDataArrays si le tableau tient dans un message, sinon une série de GetDataSubarrays découpés selon les dimensions. open et close ne font rien ; isOpened suit l'état de la session. Les tableaux de chaînes ne sont pas pris en charge. FesapiHdfProxyFactory le fabrique pour un dépôt.

FesapiHdfProxy is a fesapi HDF proxy that reads arrays through ETP instead of a local .h5: each read asks GetDataArrayMetadata, then GetDataArrays if the array fits in one message, else a series of GetDataSubarrays split along dimensions. open and close do nothing; isOpened follows the session. String arrays are not supported.

### Remplir un dépôt fesapi depuis un store (filling a fesapi repository)
On donne au DataObjectRepository une FesapiHdfProxyFactory(session), on liste les ressources d'un dataspace (getResources), on lit leurs XML (getDataObjects), puis on verse chacun par addOrReplaceGsoapProxy(xml, getDataObjectType(uri), getDataspaceUri(uri)). Les représentations se lisent ensuite comme d'un EPC, les tableaux passant par ETP. FesapiHelpers fait l'inverse : buildEtpDataObjectFromEnergisticsObject, pour putDataObjects.

Give the DataObjectRepository a FesapiHdfProxyFactory(session), list a dataspace's resources (getResources), read their XML (getDataObjects), and load each with addOrReplaceGsoapProxy. Representations then read as from an EPC, arrays coming through ETP. FesapiHelpers does the reverse: buildEtpDataObjectFromEnergisticsObject, for putDataObjects.

### SSL et TLS (SSL and TLS)
Avec l'option WITH_ETP_SSL (activée par défaut dans CMake) et OpenSSL, fetpapi ouvre une SslClientSession quand le port vaut 443 ou que setForceTls(true) est donné. Le contexte exige TLS 1.2 au moins (SSLv2, SSLv3, TLS 1.0 et 1.1 refusés), charge les certificats par défaut du système et ceux de setAdditionalCertificates. Sans cette option, seules les sessions en clair (ws://) existent.

With WITH_ETP_SSL (on by default in CMake) and OpenSSL, fetpapi opens an SslClientSession when the port is 443 or setForceTls(true) is given. The context requires TLS 1.2 or later, loads the system's default certificates and those of setAdditionalCertificates. Without the option, only plain (ws://) sessions exist.

### Échec de connexion (connection failures)
Si la poignée de main WebSocket échoue, fetpapi affiche le code d'erreur et rappelle trois causes fréquentes : certains serveurs exigent une barre oblique finale dans l'URL, l'en-tête data-partition-id peut manquer, le jeton peut avoir expiré. Un appel bloquant sans réponse à temps lève « Time out waiting for a response of message id … ». fetpapi n'envoie pas de message plus gros que la taille négociée : une réponse trop grosse devient une exception de protocole (code 17).

If the WebSocket handshake fails, fetpapi prints the error and recalls three frequent causes: some servers require a trailing slash in the URL, the data-partition-id header may be missing, the token may have expired. A blocking call without a timely answer throws "Time out waiting for a response". fetpapi never sends a message larger than the negotiated size.

### Flux client type (typical client workflow)
Créer InitializationParameters(uuid, url) et ses en-têtes ; createClientSession(&params, "Bearer <jeton>") ; donner au dépôt fesapi une FesapiHdfProxyFactory ; lancer run sur un fil ; attendre que isEtpSessionClosed soit faux ; getDataspaces ; getResources sur le dataspace choisi ; getDataObjects puis addOrReplaceGsoapProxy ; lire géométries et propriétés avec fesapi ; enfin close.

Create InitializationParameters(uuid, url) and headers; createClientSession(&params, "Bearer <token>"); give the fesapi repository a FesapiHdfProxyFactory; start run on a thread; wait until isEtpSessionClosed is false; getDataspaces; getResources on the chosen dataspace; getDataObjects then addOrReplaceGsoapProxy; read with fesapi; close.

### fetpapi dans FESPP (fetpapi in FESPP)
Le plugin FESPP, compilé avec WITH_ETP_SSL, suit ce flux : en-tête data-partition-id, autorisation « Bearer <jeton> » ou « Basic <jeton> », gestionnaires Dataspace, Discovery, Store et DataArray, session sur un fil détaché, 5 secondes pour ouvrir, puis jusqu'à 10 essais de getDataspaces espacés de 200 ms ; « eml:/// » est ajouté à la liste. Pour charger un dataspace, getResources tente self (profondeur 1), targets (1), puis targets (0), selon le serveur.

The FESPP plugin, built WITH_ETP_SSL, follows this flow: data-partition-id header, "Bearer <token>" or "Basic <token>", four handlers, session on a detached thread, 5 seconds to open, up to 10 getDataspaces tries; "eml:///" is added to the list. To load a dataspace, getResources tries self (depth 1), targets (1), then targets (0).
